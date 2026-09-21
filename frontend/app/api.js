const BASE = "";
const ADMIN_PASSPHRASE_KEY = "pdi_admin_passphrase";

// PR13 (Viewer/Admin permission gate): the passphrase lives only in this
// tab's sessionStorage - not a login session, nothing server-side to
// expire. Every mutating request echoes it back in a header; the backend
// no-ops the check entirely for a deployment that never configured a
// passphrase (config/settings.py's admin_passphrase, empty by default).
function adminHeaders() {
  try {
    const passphrase = sessionStorage.getItem(ADMIN_PASSPHRASE_KEY);
    return passphrase ? { "X-Admin-Passphrase": passphrase } : {};
  } catch {
    return {};
  }
}

async function errorFromResponse(res) {
  const text = await res.text();
  let message = text;
  let diagnosticId;
  let body;
  try {
    body = JSON.parse(text);
    message = body.message || body.detail || text;
    diagnosticId = body.diagnosticId;
  } catch {
    // Not a JSON body (e.g. a proxy/framework error page) - fall back to raw text.
  }
  const error = new Error(`${res.status} ${message}`);
  error.status = res.status;
  if (diagnosticId) error.diagnosticId = diagnosticId;
  // PR12: a 412 conflict's body carries `currentRow` (the latest server
  // state) so the caller can show it instead of just "someone else edited
  // this" - attach the whole parsed body, not just message/diagnosticId.
  if (body) error.body = body;
  return error;
}

async function json(res) {
  if (!res.ok && res.status !== 409) throw await errorFromResponse(res);
  return res.json();
}

export const api = {
  uploadDocument: (file, force = false) => {
    const form = new FormData();
    form.append("file", file);
    const qs = force ? "?force=true" : "";
    return fetch(`${BASE}/api/documents${qs}`, { method: "POST", body: form, headers: adminHeaders() }).then(async (res) => {
      // 409 (duplicate) is a normal, expected outcome the caller branches
      // on via `status` - every other non-2xx (400 bad file, 423 already
      // processing, 503 queue full, ...) must throw, or the upload looks
      // like it silently did nothing instead of surfacing why it failed.
      if (!res.ok && res.status !== 409) throw await errorFromResponse(res);
      const body = await res.json();
      return { status: res.status, body };
    });
  },
  listDocuments: () => fetch(`${BASE}/api/documents`).then(json),
  getDocument: (id) => fetch(`${BASE}/api/documents/${id}`).then(json),
  deleteDocument: (id) => fetch(`${BASE}/api/documents/${id}`, { method: "DELETE", headers: adminHeaders() }).then(json),
  reprocessDocument: (id) =>
    fetch(`${BASE}/api/documents/${id}/reprocess`, { method: "POST", headers: adminHeaders() }).then(json),
  pdfUrl: (id) => `${BASE}/api/documents/${id}/pdf`,
  allProducts: () => fetch(`${BASE}/api/products`).then(json),
  dashboardState: () => fetch(`${BASE}/api/state`).then(json),
  exportUrl: () => `${BASE}/api/export.xlsx`,
  exportExpiryDashboardUrl: () => `${BASE}/api/export/expiry-dashboard.csv`,

  getDepartmentDivisions: () => fetch(`${BASE}/api/departments/divisions`).then(json),
  getDivisions: (docId) => fetch(`${BASE}/api/analytics/documents/${docId}/divisions`).then(json),
  getDivisionDepartments: (docId, divisionCode) =>
    fetch(`${BASE}/api/analytics/documents/${docId}/divisions/${divisionCode}/departments`).then(json),

  getProduct: (rowId) => fetch(`${BASE}/api/products/${rowId}`).then(json),
  patchProduct: (rowId, field, value, reason, expectedUpdatedAt) =>
    fetch(`${BASE}/api/products/${rowId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ field, value, reason, expectedUpdatedAt }),
    }).then(json),
  productHistory: (rowId) => fetch(`${BASE}/api/products/${rowId}/history`).then(json),
  undoCorrection: (rowId, correctionId) =>
    fetch(`${BASE}/api/products/${rowId}/undo`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify({ correctionId }),
    }).then(json),
  confirmReview: (rowId) =>
    fetch(`${BASE}/api/review/${rowId}/confirm`, { method: "POST", headers: adminHeaders() }).then(json),

  listLocalMaster: (search = "") =>
    fetch(`${BASE}/api/master/local${search ? `?search=${encodeURIComponent(search)}` : ""}`).then(json),
  addLocalMaster: (entry) =>
    fetch(`${BASE}/api/master/local`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...adminHeaders() },
      body: JSON.stringify(entry),
    }).then(json),
  officialMasterCount: () => fetch(`${BASE}/api/master/official/count`).then(json),
  officialMasterLookup: (barcode) =>
    fetch(`${BASE}/api/master/official/lookup?barcode=${encodeURIComponent(barcode)}`).then(json),
  masterSnapshotStatus: () => fetch(`${BASE}/api/master/snapshot/status`).then(json),
  expiryLinkSummary: () => fetch(`${BASE}/api/expiry-link/summary`).then(json),
  importMasterCatalog: (file) => {
    const form = new FormData();
    form.append("file", file);
    return fetch(`${BASE}/api/master/import`, { method: "POST", body: form, headers: adminHeaders() }).then(json);
  },

  health: () => fetch(`${BASE}/api/health`).then(json),

  adminStatus: () => fetch(`${BASE}/api/auth/admin-status`).then(json),
  adminUnlock: (passphrase) =>
    fetch(`${BASE}/api/auth/admin-unlock`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ passphrase }),
    }).then(json),
  isAdminUnlocked: () => {
    try {
      return Boolean(sessionStorage.getItem(ADMIN_PASSPHRASE_KEY));
    } catch {
      return false;
    }
  },
  setAdminPassphrase: (passphrase) => {
    try {
      sessionStorage.setItem(ADMIN_PASSPHRASE_KEY, passphrase);
    } catch {
      // sessionStorage unavailable (private mode edge cases) - the unlock
      // still "worked" for this request, just won't persist across a
      // re-render; every mutating call will simply prompt again.
    }
  },
  clearAdminPassphrase: () => {
    try {
      sessionStorage.removeItem(ADMIN_PASSPHRASE_KEY);
    } catch {
      // ignore
    }
  },
};
