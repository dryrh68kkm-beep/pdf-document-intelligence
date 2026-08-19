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
};
