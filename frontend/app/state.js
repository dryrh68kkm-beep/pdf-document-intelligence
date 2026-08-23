import { api } from "./api.js";

function buildSearchIndex(product) {
  // Computed once per data refresh (not per keystroke, per the app spec's
  // caching requirement) - Thai text isn't case-folded (Thai has no case)
  // but the Latin/digit parts are, so search is case-insensitive throughout.
  const f = product.fields;
  const parts = [
    f.barcode?.value, f.article?.value, f.name?.value, f.dn_no?.value,
    f.do_no?.value, product.department, product.docFilename,
  ];
  return parts.filter(Boolean).join(" ").toLowerCase();
}

function inDocumentDateRange(documentDate, dateFrom, dateTo) {
  if (!documentDate) return !dateFrom && !dateTo;
  if (dateFrom && documentDate < dateFrom) return false;
  if (dateTo && documentDate > dateTo) return false;
  return true;
}

function buildDashboardOverview(items, divisionFilter) {
  const divisionMap = new Map();
  let amountAvailable = false;
  let allRows = 0;
  let allAmount = 0;

  items.forEach(({ document, summary }) => {
    amountAvailable = amountAvailable || Boolean(summary.amountAvailable);
    allRows += summary.documentTotals?.rowCount ?? 0;
    allAmount += summary.documentTotals?.amount ?? 0;

    (summary.divisions || []).forEach((division) => {
      if (!divisionMap.has(division.divisionCode)) {
        divisionMap.set(division.divisionCode, {
          divisionCode: division.divisionCode,
          divisionName: division.divisionName,
          rowCount: 0,
          amount: 0,
          documentIds: new Set(),
        });
      }
      const bucket = divisionMap.get(division.divisionCode);
      bucket.rowCount += division.rowCount ?? 0;
      bucket.amount += division.amount ?? 0;
      if ((division.rowCount ?? 0) > 0) bucket.documentIds.add(document.id);
    });
  });

  const divisions = [...divisionMap.values()]
    .map((division) => ({
      divisionCode: division.divisionCode,
      divisionName: division.divisionName,
      rowCount: division.rowCount,
      amount: Math.round((division.amount + Number.EPSILON) * 100) / 100,
      documentCount: division.documentIds.size,
    }))
    .sort((a, b) => a.divisionCode.localeCompare(b.divisionCode));

  const selected = divisionFilter && divisionFilter !== "all"
    ? divisions.find((division) => division.divisionCode === divisionFilter) || null
    : null;

  const totals = selected
    ? {
        rowCount: selected.rowCount,
        amount: selected.amount,
        documentCount: selected.documentCount,
      }
    : {
        rowCount: allRows,
        amount: Math.round((allAmount + Number.EPSILON) * 100) / 100,
        documentCount: items.length,
      };

  return {
    totals,
    divisions,
    amountAvailable,
    selectedDivision: selected?.divisionCode ?? "all",
  };
}

class Store {
  constructor() {
    this.state = {
      documents: [],
      dashboard: null,
      products: [],
      view: "dashboard",
      deptFilter: null,
      panel: null,
      searchQuery: "",
      currentDocumentId: null,
      dashboardDateFilter: "",
      dashboardDateFrom: "",
      dashboardDateTo: "",
      dashboardDivisionFilter: "all",
      dashboardOverview: null,
      divisionSummary: null,
      divisionDetail: null,
    };
    this._listeners = [];
    this._divisionCache = new Map();
  }

  subscribe(fn) {
    this._listeners.push(fn);
    return () => { this._listeners = this._listeners.filter((l) => l !== fn); };
  }

  set(patch) {
    Object.assign(this.state, patch);
    this._listeners.forEach((fn) => fn(this.state));
  }

  hasProcessing() {
    return this.state.documents.some((d) => d.status === "processing");
  }

  async refreshDocuments({ silent = false } = {}) {
    const documents = await api.listDocuments();
    if (silent) {
      // Progress polling should not rebuild the whole active view every 1.5s.
      // main.js updates only the sidebar/bottom progress UI for silent polls.
      Object.assign(this.state, { documents });
    } else {
      this.set({ documents });
    }
    return documents;
  }

  async refreshAll() {
    const [documents, dashboard, rawProducts] = await Promise.all([
      api.listDocuments(),
      api.dashboardState(),
      api.allProducts(),
    ]);
    const products = rawProducts.map((p) => ({ ...p, _search: buildSearchIndex(p) }));
    const previousDocumentId = this.state.currentDocumentId;
    const dateFilter = this.state.dashboardDateFilter;
    const visibleDocuments = dateFilter
      ? documents.filter((doc) => doc.documentDate === dateFilter)
      : documents;
    const currentDocumentId = visibleDocuments.some((doc) => doc.id === previousDocumentId)
      ? previousDocumentId
      : visibleDocuments[0]?.id ?? null;

    this._divisionCache.clear();
    this.set({ documents, dashboard, products, currentDocumentId, dashboardOverview: null });
    await Promise.all([this.refreshDivisions(), this.refreshDashboardOverview()]);
  }

  async _getDivisionSummary(docId) {
    if (this._divisionCache.has(docId)) return this._divisionCache.get(docId);
    try {
      const summary = await api.getDivisions(docId);
      this._divisionCache.set(docId, summary);
      return summary;
    } catch {
      this._divisionCache.set(docId, null);
      return null;
    }
  }

  async refreshDashboardOverview() {
    const { dashboardDateFrom, dashboardDateTo, dashboardDivisionFilter } = this.state;
    const documents = this.state.documents.filter(
      (doc) => doc.status === "complete" && inDocumentDateRange(doc.documentDate, dashboardDateFrom, dashboardDateTo),
    );
    const pairs = await Promise.all(
      documents.map(async (document) => ({ document, summary: await this._getDivisionSummary(document.id) })),
    );
    const usable = pairs.filter((item) => item.summary);
    this.set({ dashboardOverview: buildDashboardOverview(usable, dashboardDivisionFilter) });
  }

  async setDashboardOverviewFilters({ dateFrom, dateTo, division } = {}) {
    const patch = {
      dashboardDateFrom: dateFrom ?? this.state.dashboardDateFrom,
      dashboardDateTo: dateTo ?? this.state.dashboardDateTo,
      dashboardDivisionFilter: division ?? this.state.dashboardDivisionFilter,
      dashboardOverview: null,
    };
    this.set(patch);
    await this.refreshDashboardOverview();
  }

  async refreshDivisions() {
    const doc = this.state.documents.find((d) => d.id === this.state.currentDocumentId);
    if (!doc || doc.status !== "complete") {
      this.set({ divisionSummary: null });
      return;
    }
    const divisionSummary = await this._getDivisionSummary(doc.id);
    this.set({ divisionSummary });
  }

  async selectDashboardDocument(docId) {
    if (docId === this.state.currentDocumentId) return;
    this.set({ currentDocumentId: docId, divisionSummary: null, divisionDetail: null });
    await this.refreshDivisions();
  }

  async setDashboardDateFilter(documentDate) {
    const dashboardDateFilter = documentDate || "";
    const visibleDocuments = dashboardDateFilter
      ? this.state.documents.filter((doc) => doc.documentDate === dashboardDateFilter)
      : this.state.documents;
    const currentDocumentId = visibleDocuments.some((doc) => doc.id === this.state.currentDocumentId)
      ? this.state.currentDocumentId
      : visibleDocuments[0]?.id ?? null;
    this.set({ dashboardDateFilter, currentDocumentId, divisionSummary: null, divisionDetail: null });
    await this.refreshDivisions();
  }

  async openDivision(divisionCode) {
    const docId = this.state.currentDocumentId;
    const detail = await api.getDivisionDepartments(docId, divisionCode);
    this.set({ view: "divisionDetail", panel: null, divisionDetail: detail });
  }

  openPanel(panel) { this.set({ panel }); }
  closePanel() { this.set({ panel: null }); }

  navigate(view, extra = {}) {
    this.set({ view, panel: null, ...extra });
  }
}

export const store = new Store();
