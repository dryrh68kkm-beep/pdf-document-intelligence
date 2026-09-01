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

// `items` covers only the documents whose per-document Division summary
// fetch actually succeeded - a document in the selected date range whose
// summary errored has no per-division/amount breakdown to contribute here,
// there's no way around that. But `scope` (all-"all"-selection only)
// carries the *real* documentCount/rowCount for the whole in-range set,
// computed independently by the caller from the same documents/products
// arrays Documents/Products use - so a summary failure never silently
// shrinks the headline counts, only the money/division breakdown, and
// `incompleteDocumentCount` says so explicitly instead of the numbers
// just quietly not adding up (user requirement: never drop a document
// whose Division summary errored without saying so).
function buildDashboardOverview(items, divisionFilter, scope = {}) {
  const divisionMap = new Map();
  let amountAvailable = false;
  let allRows = 0;
  let allAmount = 0;
  // PR10 (Data Accuracy Gate): a document whose own declared Total didn't
  // match the sum of its extracted line items (reconciled === false) still
  // contributes to these grand totals - excluding it outright would make
  // numbers silently vanish, which is its own kind of surprising. Instead
  // this counts how much of the headline total came from unreconciled
  // documents, so the Dashboard can warn instead of presenting every
  // number as equally trustworthy.
  let unreconciledDocumentCount = 0;
  let unreconciledAmount = 0;

  items.forEach(({ document, summary }) => {
    amountAvailable = amountAvailable || Boolean(summary.amountAvailable);
    allRows += summary.documentTotals?.rowCount ?? 0;
    allAmount += summary.documentTotals?.amount ?? 0;
    if (document.reconciled === false) {
      unreconciledDocumentCount += 1;
      unreconciledAmount += summary.documentTotals?.amount ?? 0;
    }

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

  const incompleteDocumentCount = scope.incompleteDocumentCount ?? 0;

  const totals = selected
    ? {
        // A single-Division slice is inherently derived from per-document
        // Division summaries (there's no other source for "rows in this
        // Division") - scope's independent counts don't apply here.
        rowCount: selected.rowCount,
        amount: selected.amount,
        documentCount: selected.documentCount,
      }
    : {
        // Same source Documents/Products use (see _computeDashboardOverview),
        // not a sum over `items` - so a Division-summary failure never
        // shrinks these two, only the amount/division breakdown below.
        rowCount: scope.rowCount ?? allRows,
        amount: Math.round((allAmount + Number.EPSILON) * 100) / 100,
        documentCount: scope.documentCount ?? items.length,
      };

  return {
    totals,
    divisions,
    amountAvailable,
    selectedDivision: selected?.divisionCode ?? "all",
    unreconciledDocumentCount,
    unreconciledAmount: Math.round((unreconciledAmount + Number.EPSILON) * 100) / 100,
    incompleteDocumentCount,
    isDataIncomplete: incompleteDocumentCount > 0,
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
      // Display label for deptFilter when it's a Division-level array filter
      // (e.g. from the Dashboard's "มูลค่าตามฝ่าย" table) - a plain string
      // deptFilter doesn't need this, it's shown directly as the title.
      deptFilterLabel: null,
      // "departments" when deptFilter was set by clicking a card on the
      // Departments page - lets Products' back-link return there instead of
      // just clearing the filter and staying on Products (user report:
      // clicking a department card had no way back to the Departments
      // summary/totals view at all).
      deptFilterFrom: null,
      panel: null,
      searchQuery: "",
      currentDocumentId: null,
      dashboardDateFilter: "",
      // Dashboard header filters (user request): a document-date RANGE plus
      // an optional single-Division filter, replacing the earlier
      // day-by-day navigator. "" for either date bound means unbounded (all
      // documents). Always filters on documentDate, never uploadedAt - see
      // inDocumentDateRange() above.
      dashboardDateFrom: "",
      dashboardDateTo: "",
      dashboardDivisionFilter: "all",
      // { totals: {rowCount, amount, documentCount}, divisions: [...],
      // amountAvailable, selectedDivision } - built by
      // _computeDashboardOverview() below from each in-range document's
      // authoritative /api/analytics/documents/{id}/divisions summary
      // (Decimal-safe, sourced from the same division_for_department()
      // mapping as everywhere else) - never recomputed by guessing a
      // qty*price formula on the frontend. null until the first load's
      // per-document fetches resolve.
      dashboardOverview: null,
      divisionSummary: null,
      divisionDetail: null,
      // Flat department->division map from the master catalog (see
      // GET /api/departments/divisions) - lets any view show Division
      // above Department per row without a document-scoped division
      // summary fetch. Refreshed alongside everything else in
      // _doRefreshAll(); empty until the first load completes.
      departmentDivisions: {},
      // Surfaced in the Dashboard header (user request): when data was last
      // refreshed, and whether a refresh is in flight right now.
      dashboardLastRefreshedAt: null,
      dashboardRefreshing: false,
    };
    this._listeners = [];
    this._divisionCache = new Map();
    // Shared date scope cache. Dashboard's document-date range is the
    // application's authoritative working date scope, not a Dashboard-only
    // visual filter: Products / Review / Non-product / Documents /
    // Departments and sidebar counters all consume these same selections.
    // Cache by source-array identity + date bounds so unrelated UI renders
    // do not refilter tens of thousands of rows.
    this._dateScopeCache = {
      documentsRef: null,
      productsRef: null,
      dateFrom: null,
      dateTo: null,
      documents: [],
      products: [],
    };
    this._refreshAllInFlight = null;
    this._refreshAllQueued = false;
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

  _dateScopedSelections() {
    const { documents, products, dashboardDateFrom, dashboardDateTo } = this.state;
    const cached = this._dateScopeCache;
    if (
      cached.documentsRef === documents &&
      cached.productsRef === products &&
      cached.dateFrom === dashboardDateFrom &&
      cached.dateTo === dashboardDateTo
    ) {
      return cached;
    }

    // With no Dashboard date selected, return the original arrays so views
    // keep their existing memoization/reference behavior and pay no filter
    // cost at all.
    let scopedDocuments = documents;
    let scopedProducts = products;
    if (dashboardDateFrom || dashboardDateTo) {
      scopedDocuments = documents.filter((doc) =>
        inDocumentDateRange(doc.documentDate, dashboardDateFrom, dashboardDateTo)
      );
      const completedDocumentIds = new Set(
        scopedDocuments.filter((doc) => doc.status === "complete").map((doc) => doc.id)
      );
      scopedProducts = products.filter((product) => completedDocumentIds.has(product.docId));
    }

    Object.assign(cached, {
      documentsRef: documents,
      productsRef: products,
      dateFrom: dashboardDateFrom,
      dateTo: dashboardDateTo,
      documents: scopedDocuments,
      products: scopedProducts,
    });
    return cached;
  }

  getDateScopedDocuments() {
    return this._dateScopedSelections().documents;
  }

  getDateScopedProducts() {
    return this._dateScopedSelections().products;
  }

  _pruneDivisionCache(documents) {
    const completedIds = new Set(documents.filter((doc) => doc.status === "complete").map((doc) => doc.id));
    for (const docId of this._divisionCache.keys()) {
      if (!completedIds.has(docId)) this._divisionCache.delete(docId);
    }
  }

  invalidateDivisionSummary(docId) {
    if (docId) this._divisionCache.delete(docId);
  }

  async refreshDocuments({ silent = false } = {}) {
    const documents = await api.listDocuments();
    // A deleted/reprocessing document must not keep a stale cached Division
    // summary, but completed documents that did not change can safely retain
    // theirs. This keeps the existing Dashboard path while avoiding repeated
    // re-fetches for every historical document.
    this._pruneDivisionCache(documents);
    if (silent) {
      // Progress polling should not rebuild the whole active view every 1.5s.
      // main.js updates only the sidebar/bottom progress UI for silent polls.
      Object.assign(this.state, { documents });
    } else {
      this.set({ documents });
    }
    return documents;
  }

  // Several independent triggers can call refreshAll() around the same
  // moment (the topbar refresh button, an upload finishing, a background
  // poll noticing a document completed) - with no guard, two overlapping
  // calls each run their own Promise.all/set(), and whichever's fetch
  // happens to resolve LAST wins even if it was the one that *started*
  // first, silently reverting the UI to older data. Concurrent callers
  // instead share the in-flight run; a call that arrives after fetching has
  // already started queues exactly one more run so the caller's own
  // "refresh now" intent is still honored once the current run finishes.
  async refreshAll() {
    if (this._refreshAllInFlight) {
      this._refreshAllQueued = true;
      return this._refreshAllInFlight;
    }
    this.set({ dashboardRefreshing: true });
    this._refreshAllInFlight = (async () => {
      try {
        do {
          this._refreshAllQueued = false;
          await this._doRefreshAll();
        } while (this._refreshAllQueued);
        this.set({ dashboardLastRefreshedAt: new Date().toISOString() });
      } finally {
        this._refreshAllInFlight = null;
        this.set({ dashboardRefreshing: false });
      }
    })();
    return this._refreshAllInFlight;
  }

  async _doRefreshAll() {
    const [documents, dashboard, rawProducts, departmentDivisions] = await Promise.all([
      api.listDocuments(),
      api.dashboardState(),
      api.allProducts(),
      api.getDepartmentDivisions(),
    ]);
    // Each product row's own document is looked up once here (rather than
    // per-render in every view) so any view can show "which document date
    // did this row come in on" without its own documents/products join -
    // the same documentDate field Dashboard/Products/Documents already
    // scope by (see inDocumentDateRange() above), just carried onto the row.
    const documentDateById = new Map(documents.map((doc) => [doc.id, doc.documentDate]));
    const products = rawProducts.map((p) => ({
      ...p,
      documentDate: documentDateById.get(p.docId) ?? null,
      _search: buildSearchIndex(p),
    }));
    const previousDocumentId = this.state.currentDocumentId;
    const dateFilter = this.state.dashboardDateFilter;
    const visibleDocuments = dateFilter
      ? documents.filter((doc) => doc.documentDate === dateFilter)
      : documents;
    const currentDocumentId = visibleDocuments.some((doc) => doc.id === previousDocumentId)
      ? previousDocumentId
      : visibleDocuments[0]?.id ?? null;

    // Keep existing per-document Division summaries instead of clearing the
    // whole cache on every refresh. Deleted/reprocessing IDs are removed; an
    // edited document is invalidated explicitly before refreshAll().
    this._pruneDivisionCache(documents);
    this.set({ documents, dashboard, products, currentDocumentId, departmentDivisions });
    // Combined into a single set() instead of two independent ones (each of
    // refreshDivisions()/refreshDashboardOverview() used to call this.set()
    // on its own, so whichever Promise settled first fired a full re-render
    // with a half-updated state, then the second settling fired another -
    // two redundant full-view rebuilds for what is really one logical
    // "background sections finished loading" update).
    const [divisionSummary, dashboardOverview] = await Promise.all([
      this._computeDivisionSummary(currentDocumentId, documents),
      this._computeDashboardOverview(documents),
    ]);
    this.set({ divisionSummary, dashboardOverview });
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

  async _computeDashboardOverview(documents = this.state.documents, products = this.state.products) {
    const { dashboardDateFrom, dashboardDateTo, dashboardDivisionFilter } = this.state;
    const inRange = documents.filter(
      (doc) => doc.status === "complete" && inDocumentDateRange(doc.documentDate, dashboardDateFrom, dashboardDateTo),
    );
    const pairs = await Promise.all(
      inRange.map(async (document) => ({ document, summary: await this._getDivisionSummary(document.id) })),
    );
    // documentCount/rowCount come from the same date-scoped documents/products
    // arrays Products.js and Documents use (see getDateScopedDocuments()/
    // getDateScopedProducts()), not from summing over per-document Division
    // summaries - so a Division-summary fetch failure below never shrinks
    // these two headline counts, it only leaves that document out of the
    // amount/Division breakdown and is surfaced via incompleteDocumentCount.
    const inRangeDocIds = new Set(inRange.map((doc) => doc.id));
    const rowCount = products.filter((p) => !p.suspectedNonProduct && inRangeDocIds.has(p.docId)).length;
    const incompleteDocumentCount = pairs.filter((item) => !item.summary).length;
    const usable = pairs.filter((item) => item.summary);
    return buildDashboardOverview(usable, dashboardDivisionFilter, {
      documentCount: inRange.length,
      rowCount,
      incompleteDocumentCount,
    });
  }

  async refreshDashboardOverview() {
    this.set({ dashboardOverview: await this._computeDashboardOverview() });
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

  async _computeDivisionSummary(currentDocumentId = this.state.currentDocumentId, documents = this.state.documents) {
    const doc = documents.find((d) => d.id === currentDocumentId);
    if (!doc || doc.status !== "complete") return null;
    return this._getDivisionSummary(doc.id);
  }

  async refreshDivisions() {
    this.set({ divisionSummary: await this._computeDivisionSummary() });
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
