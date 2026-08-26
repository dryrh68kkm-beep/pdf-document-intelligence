import { api } from "./api.js";
import { store } from "./state.js";
import { icons } from "./icons.js";
import { renderSidebar } from "./components/sidebar.js";
import { renderProductDetail, detailPanelIsDirty, detailPanelReset, setDirtyChangeListener } from "./components/detailPanel.js";
import { escapeHtml } from "./escape.js";

const VIEWS = {
  dashboard: () => import("./views/dashboard.js").then((m) => m.renderDashboard),
  divisionDetail: () => import("./views/divisionDetail.js").then((m) => m.renderDivisionDetail),
  departments: () => import("./views/departments.js").then((m) => m.renderDepartments),
  products: () => import("./views/products.js").then((m) => m.renderProducts),
  review: () => import("./views/review.js").then((m) => m.renderReview),
  nonproduct: () => import("./views/nonproduct.js").then((m) => m.renderNonProduct),
  documents: () => import("./views/documents.js").then((m) => m.renderDocuments),
  productMaster: () => import("./views/productMaster.js").then((m) => m.renderProductMaster),
};

const workspaceEl = document.getElementById("workspace");
const sidePanelEl = document.getElementById("sidePanel");
const fileInput = document.getElementById("fileInput");
const dragOverlay = document.getElementById("dragOverlay");
const modalBackdrop = document.getElementById("modalBackdrop");
const modalBox = document.getElementById("modalBox");
const addFilesBtn = document.getElementById("addFilesBtn");

let uploadInProgress = false;
let pollInProgress = false;
let pollFailureCount = 0;

// render() is async only because loading a view module the first time is a
// dynamic import() - store.subscribe(render) fires it on every store.set(),
// so two state changes close together (e.g. two unrelated background
// refreshes) can leave two render() calls in flight at once. Without a
// guard, whichever's import() happens to resolve LAST wins the DOM write,
// even if it started first - a real, reproducible source of duplicate
// full-view rebuilds. renderGeneration lets a render() call that's no
// longer the latest bail out before writing the DOM, instead of racing the
// newer one.
let renderGeneration = 0;
async function render() {
  const myGeneration = ++renderGeneration;
  renderSidebar(store);
  const renderView = await VIEWS[store.state.view]();
  if (myGeneration !== renderGeneration) return; // a newer render() already started - it owns the DOM now
  // Passed down to the view so its own post-await DOM writes (currently
  // only productMaster.js does real async work inside its render function
  // - every other view's data is already loaded by the time this runs)
  // can bail out if a newer render() has since taken over #workspace,
  // the same way this function itself just checked above. Harmless for a
  // synchronous view to ignore.
  const isStale = () => myGeneration !== renderGeneration;
  await renderView(workspaceEl, store, isStale);
  if (isStale()) return;
  renderSidePanel();
  renderBottomBar();
}

function closePanelWithDirtyCheck() {
  if (detailPanelIsDirty()) {
    store.set({
      confirmDialog: {
        title: "มีการแก้ไขที่ยังไม่ได้บันทึก",
        message: "ปิดหน้าต่างนี้จะทิ้งการแก้ไขที่ยังไม่ได้บันทึก ต้องการปิดหรือไม่?",
        onConfirm: () => { detailPanelReset(); store.closePanel(); },
      },
    });
    document.dispatchEvent(new CustomEvent("show-confirm"));
    return;
  }
  detailPanelReset();
  store.closePanel();
}

function renderSidePanel() {
  const { panel } = store.state;
  if (!panel) {
    sidePanelEl.classList.remove("open");
    return;
  }
  sidePanelEl.classList.add("open");
  if (panel.type === "product") {
    const closeBtn = renderProductDetail(sidePanelEl, panel.data, store);
    closeBtn.addEventListener("click", closePanelWithDirtyCheck);
  }
}

// When a correction/undo saves, refresh all data (dashboard/products
// recalculate from the DB, never patched in place) and re-open the panel
// on the freshly-saved row so evidence + history reflect the save. Only the
// edited document's existing Division summary is invalidated; historical
// documents keep their cached summaries.
document.addEventListener("product-saved", async (e) => {
  const changedDocId = store.state.panel?.data?.docId;
  store.invalidateDivisionSummary(changedDocId);
  await store.refreshAll();
  const rowId = e.detail.rowId;
  const fresh = store.state.products.find((p) => p.rowId === rowId);
  if (fresh) store.openPanel({ type: "product", rowId, data: fresh });
});

function renderBottomBar() {
  const { documents } = store.state;
  const fileStat = document.getElementById("fileStat");
  const strip = document.getElementById("processingStrip");
  if (documents.length === 0) {
    fileStat.textContent = "ยังไม่มีเอกสาร";
  } else {
    const totalPages = documents.reduce((a, d) => a + (d.pages || 0), 0);
    fileStat.innerHTML = `<b>${documents.length}</b> Files · <b>${totalPages}</b> Pages`;
  }
  if (pollFailureCount >= 2) {
    strip.innerHTML = `<div class="processing-item connection-warning">
      <span>⚠ เชื่อมต่อเซิร์ฟเวอร์ไม่สำเร็จ</span>
      <button class="btn btn-sm" id="connectionRetryBtn" type="button">ลองใหม่</button>
    </div>`;
    strip.querySelector("#connectionRetryBtn")?.addEventListener("click", () => pollLoop());
    return;
  }
  const processing = documents.filter((d) => d.status === "processing");
  strip.innerHTML = processing
    .map((d) => {
      const pct = d.progress.total ? Math.round((d.progress.current / d.progress.total) * 100) : 5;
      return `<div class="processing-item">
        <span>${escapeHtml(d.filename)}: ${escapeHtml(d.progress.stage)}</span>
        <div class="mini-progress"><div style="width:${pct}%"></div></div>
      </div>`;
    })
    .join("");
}

function renderLightweightProgressUi() {
  renderSidebar(store);
  renderBottomBar();
}

function setUploadBusy(busy) {
  uploadInProgress = busy;
  addFilesBtn.disabled = busy;
  fileInput.disabled = busy;
  addFilesBtn.setAttribute("aria-busy", busy ? "true" : "false");
  if (busy) {
    addFilesBtn.dataset.originalText = addFilesBtn.textContent;
    addFilesBtn.textContent = "กำลังเพิ่มไฟล์...";
  } else if (addFilesBtn.dataset.originalText) {
    addFilesBtn.textContent = addFilesBtn.dataset.originalText;
    delete addFilesBtn.dataset.originalText;
  }
}

function showUploadError(error) {
  modalBox.innerHTML = `
    <h3>เพิ่มไฟล์ไม่สำเร็จ</h3>
    <p>${escapeHtml(String(error?.message || error))}</p>
    <div class="modal-actions">
      <button class="btn btn-primary" id="uploadErrorOk">ตกลง</button>
    </div>
  `;
  modalBackdrop.classList.add("open");
  modalBox.querySelector("#uploadErrorOk").addEventListener("click", () => modalBackdrop.classList.remove("open"));
}

async function uploadFiles(fileList) {
  if (uploadInProgress) return;
  const files = Array.from(fileList).filter((file) => file.name.toLowerCase().endsWith(".pdf"));
  if (files.length === 0) return;

  setUploadBusy(true);
  try {
    for (const file of files) {
      const { status, body } = await api.uploadDocument(file);
      if (status === 409) showDuplicateDialog(file, body.existingDocument);
    }
    await store.refreshDocuments({ silent: true });
    renderLightweightProgressUi();
    if (!store.hasProcessing()) await store.refreshAll();
  } catch (error) {
    showUploadError(error);
  } finally {
    setUploadBusy(false);
  }
}

async function reprocessDuplicate(file) {
  if (uploadInProgress) return;
  setUploadBusy(true);
  try {
    await api.uploadDocument(file, true);
    await store.refreshDocuments({ silent: true });
    renderLightweightProgressUi();
    if (!store.hasProcessing()) await store.refreshAll();
  } catch (error) {
    showUploadError(error);
  } finally {
    setUploadBusy(false);
  }
}

function showDuplicateDialog(file, existing) {
  modalBox.innerHTML = `
    <h3>ไฟล์นี้มีอยู่ในระบบแล้ว</h3>
    <p>${escapeHtml(existing.filename)} — ต้องการประมวลผลเอกสารเดิมอีกครั้งหรือไม่? ข้อมูลที่ผู้ใช้แก้ไขและประวัติการแก้ไขจะยังคงอยู่</p>
    <div class="modal-actions">
      <button class="btn" id="dupCancel">ยกเลิก</button>
      <button class="btn btn-primary" id="dupAdd">ประมวลผลอีกครั้ง</button>
    </div>
  `;
  modalBackdrop.classList.add("open");
  modalBox.querySelector("#dupCancel").addEventListener("click", () => modalBackdrop.classList.remove("open"));
  modalBox.querySelector("#dupAdd").addEventListener("click", async () => {
    modalBackdrop.classList.remove("open");
    await reprocessDuplicate(file);
  });
}

// Generic retryable-error notification, reused by any view (Documents,
// Product Master, ...) for an action that failed - always a clear message
// with an explicit way to try again, never a silent console.error.
document.addEventListener("show-error", () => {
  const cfg = store.state.errorDialog;
  if (!cfg) return;
  modalBox.innerHTML = `
    <h3>${escapeHtml(cfg.title)}</h3>
    <p>${escapeHtml(cfg.message)}</p>
    ${
      cfg.diagnosticId
        ? `<p class="diagnostic-id">รหัสข้อผิดพลาด: <code>${escapeHtml(cfg.diagnosticId)}</code> <button class="btn btn-small" id="errorCopyId">คัดลอกรหัส</button></p>`
        : ""
    }
    <div class="modal-actions">
      ${cfg.onRetry ? `<button class="btn" id="errorCancel">ปิด</button><button class="btn btn-primary" id="errorRetry">ลองใหม่</button>` : `<button class="btn btn-primary" id="errorCancel">ตกลง</button>`}
    </div>
  `;
  modalBackdrop.classList.add("open");
  modalBox.querySelector("#errorCancel").addEventListener("click", () => modalBackdrop.classList.remove("open"));
  modalBox.querySelector("#errorRetry")?.addEventListener("click", async () => {
    modalBackdrop.classList.remove("open");
    await cfg.onRetry();
  });
  modalBox.querySelector("#errorCopyId")?.addEventListener("click", () => {
    navigator.clipboard?.writeText(cfg.diagnosticId).catch(() => {});
  });
});

document.addEventListener("show-confirm", () => {
  const cfg = store.state.confirmDialog;
  if (!cfg) return;
  modalBox.innerHTML = `
    <h3>${escapeHtml(cfg.title)}</h3>
    <p>${escapeHtml(cfg.message)}</p>
    <div class="modal-actions">
      <button class="btn" id="confirmCancel">ยกเลิก</button>
      <button class="btn btn-primary" id="confirmOk">ยืนยัน</button>
    </div>
  `;
  modalBackdrop.classList.add("open");
  modalBox.querySelector("#confirmCancel").addEventListener("click", () => modalBackdrop.classList.remove("open"));
  modalBox.querySelector("#confirmOk").addEventListener("click", async () => {
    modalBackdrop.classList.remove("open");
    await cfg.onConfirm();
  });
});

addFilesBtn.addEventListener("click", () => {
  if (!uploadInProgress) fileInput.click();
});
fileInput.addEventListener("change", (e) => {
  const files = Array.from(e.target.files || []);
  fileInput.value = "";
  uploadFiles(files);
});

let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  if (uploadInProgress || !e.dataTransfer?.types?.includes("Files")) return;
  dragDepth++;
  dragOverlay.classList.add("active");
});
window.addEventListener("dragleave", () => {
  dragDepth = Math.max(0, dragDepth - 1);
  if (dragDepth === 0) dragOverlay.classList.remove("active");
});
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  dragOverlay.classList.remove("active");
  if (!uploadInProgress && e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files);
});

document.getElementById("exportBtnIcon").innerHTML = icons.download;
document.getElementById("exportBtn").addEventListener("click", () => {
  window.location.href = api.exportUrl();
});

// Filter icon-button: decorative on views without an inline filter bar,
// focuses the first filter control already rendered by the active view
// (department/status/etc. selects that already exist per-view) when one is
// present - no new filtering behavior is introduced here.
document.getElementById("topbarFilterBtn").innerHTML = icons.filter;
document.getElementById("topbarFilterBtn").addEventListener("click", () => {
  workspaceEl.querySelector(".filter-chip-bar select, .filter-bar select")?.focus();
});

document.getElementById("topbarRefreshBtn").innerHTML = icons.refresh;
document.getElementById("topbarRefreshBtn").addEventListener("click", () => {
  store.refreshAll();
});

let searchDebounce = null;
document.getElementById("globalSearch").addEventListener("input", (e) => {
  clearTimeout(searchDebounce);
  const val = e.target.value;
  searchDebounce = setTimeout(() => {
    // deptFilterLabel must be cleared explicitly here too - see the same
    // comment in departments.js's deptCard(): store.navigate() only
    // overwrites the keys it's given, so a stale label from an earlier
    // Division-row click would otherwise keep showing as the Products
    // page title even after deptFilter itself is cleared for this search.
    store.navigate("products", { deptFilter: null, deptFilterLabel: null, searchQuery: val });
  }, 200);
});

async function pollLoop() {
  if (pollInProgress) return;
  pollInProgress = true;
  let nextDelay = 5000;

  try {
    const wasProcessing = store.hasProcessing();
    await store.refreshDocuments({ silent: true });
    const isProcessing = store.hasProcessing();
    pollFailureCount = 0;
    renderLightweightProgressUi();

    if (wasProcessing && !isProcessing) await store.refreshAll();
    nextDelay = isProcessing ? 1500 : 5000;
  } catch (error) {
    console.error("poll failed", error);
    pollFailureCount++;
    renderLightweightProgressUi();
    nextDelay = 5000;
  } finally {
    pollInProgress = false;
    setTimeout(pollLoop, nextDelay);
  }
}

store.subscribe(render);

function showInitError(error) {
  workspaceEl.innerHTML = `
    <div class="empty-state" style="padding:80px 20px;">
      <div class="icon">⚠</div>
      <div class="title">โหลดข้อมูลไม่สำเร็จ</div>
      <div>${escapeHtml(String(error?.message || error))}</div>
      <button class="btn btn-primary" id="initRetryBtn" style="margin-top:14px;">ลองใหม่</button>
    </div>`;
  document.getElementById("initRetryBtn")?.addEventListener("click", init);
}

async function init() {
  try {
    await store.refreshAll();
    pollLoop();
  } catch (error) {
    console.error("initial load failed", error);
    showInitError(error);
  }
}

init();
