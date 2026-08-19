const BASE = "";

async function json(res) {
  if (!res.ok && res.status !== 409) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  uploadDocument: (file, force = false) => {
    const form = new FormData();
    form.append("file", file);
    const qs = force ? "?force=true" : "";
    return fetch(`${BASE}/api/documents${qs}`, { method: "POST", body: form }).then(async (res) => {
      const body = await res.json();
      return { status: res.status, body };
    });
  },
  listDocuments: () => fetch(`${BASE}/api/documents`).then(json),
  getDocument: (id) => fetch(`${BASE}/api/documents/${id}`).then(json),
  deleteDocument: (id) => fetch(`${BASE}/api/documents/${id}`, { method: "DELETE" }).then(json),
  reprocessDocument: (id) => fetch(`${BASE}/api/documents/${id}/reprocess`, { method: "POST" }).then(json),
  pdfUrl: (id) => `${BASE}/api/documents/${id}/pdf`,
  allProducts: () => fetch(`${BASE}/api/products`).then(json),
  dashboardState: () => fetch(`${BASE}/api/state`).then(json),
  exportUrl: () => `${BASE}/api/export.xlsx`,

  getProduct: (rowId) => fetch(`${BASE}/api/products/${rowId}`).then(json),
  patchProduct: (rowId, field, value, reason) =>
    fetch(`${BASE}/api/products/${rowId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ field, value, reason }),
    }).then(json),
  productHistory: (rowId) => fetch(`${BASE}/api/products/${rowId}/history`).then(json),
  undoCorrection: (rowId, correctionId) =>
    fetch(`${BASE}/api/products/${rowId}/undo`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ correctionId }),
    }).then(json),
  confirmReview: (rowId) => fetch(`${BASE}/api/review/${rowId}/confirm`, { method: "POST" }).then(json),

  listLocalMaster: (search = "") =>
    fetch(`${BASE}/api/master/local${search ? `?search=${encodeURIComponent(search)}` : ""}`).then(json),
  addLocalMaster: (entry) =>
    fetch(`${BASE}/api/master/local`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(entry),
    }).then(json),
  officialMasterCount: () => fetch(`${BASE}/api/master/official/count`).then(json),

  health: () => fetch(`${BASE}/api/health`).then(json),
};
