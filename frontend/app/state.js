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
      divisionSummary: null,
      divisionDetail: null,
    };
    this._listeners = [];
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

  async refreshDocuments() {
    const documents = await api.listDocuments();
    this.set({ documents });
    return documents;
  }

  async refreshAll() {
    const [documents, dashboard, rawProducts] = await Promise.all([
      api.listDocuments(),
      api.dashboardState(),
      api.allProducts(),
    ]);
    const products = rawProducts.map((p) => ({ ...p, _search: buildSearchIndex(p) }));
    // "Current document" for the Dashboard's Division rollup: the most
    // recently uploaded document (documents is already sorted newest
    // first by the API) - the Dashboard shows one packing list at a time.
    const currentDocumentId = documents[0]?.id ?? null;
    this.set({ documents, dashboard, products, currentDocumentId });
    await this.refreshDivisions();
  }

  async refreshDivisions() {
    const doc = this.state.documents.find((d) => d.id === this.state.currentDocumentId);
    if (!doc || doc.status !== "complete") {
      this.set({ divisionSummary: null });
      return;
    }
    try {
      const divisionSummary = await api.getDivisions(doc.id);
      this.set({ divisionSummary });
    } catch {
      this.set({ divisionSummary: null });
    }
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
