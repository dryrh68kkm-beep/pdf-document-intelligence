import { api } from "./api.js";
import { store } from "./state.js";
import { renderSidebar } from "./components/sidebar.js";
import { renderProductDetail } from "./components/detailPanel.js";

const VIEWS = {
  dashboard: () => import("./views/dashboard.js").then((m) => m.renderDashboard),
  departments: () => import("./views/departments.js").then((m) => m.renderDepartments),
  products: () => import("./views/products.js").then((m) => m.renderProducts),
  review: () => import("./views/review.js").then((m) => m.renderReview),
  nonproduct: () => import("./views/nonproduct.js").then((m) => m.renderNonProduct),
  documents: () => import("./views/documents.js").then((m) => m.renderDocuments),
};

const workspaceEl = document.getElementById("workspace");
const sidePanelEl = document.getElementById("sidePanel");
const fileInput = document.getElementById("fileInput");
const dragOverlay = document.getElementById("dragOverlay");
const modalBackdrop = document.getElementById("modalBackdrop");
const modalBox = document.getElementById("modalBox");

async function render() {
  renderSidebar(store);
  const renderView = await VIEWS[store.state.view]();
  renderView(workspaceEl, store);
  renderSidePanel();
  renderBottomBar();
}

function renderSidePanel() {
  const { panel } = store.state;
  if (!panel) {
    sidePanelEl.classList.remove("open");
    return;
  }
  sidePanelEl.classList.add("open");
  if (panel.type === "product") {
    const closeBtn = renderProductDetail(sidePanelEl, panel.data);
    closeBtn.addEventListener("click", () => store.closePanel());
  }
}

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
  const processing = documents.filter((d) => d.status === "processing");
  strip.innerHTML = processing
    .map((d) => {
      const pct = d.progress.total ? Math.round((d.progress.current / d.progress.total) * 100) : 5;
      return `<div class="processing-item">
        <span>${d.filename}: ${d.progress.stage}</span>
        <div class="mini-progress"><div style="width:${pct}%"></div></div>
      </div>`;
    })
    .join("");
}

// ---------- Upload / dedupe ----------
async function uploadFiles(fileList) {
  for (const file of Array.from(fileList)) {
    if (!file.name.toLowerCase().endsWith(".pdf")) continue;
    const { status, body } = await api.uploadDocument(file);
    if (status === 409) {
      showDuplicateDialog(file, body.existingDocument);
    }
  }
  await store.refreshAll();
}

function showDuplicateDialog(file, existing) {
  modalBox.innerHTML = `
    <h3>ไฟล์นี้มีอยู่ในระบบแล้ว</h3>
    <p>${existing.filename} — เพิ่มซ้ำจะประมวลผลไฟล์เดิมอีกครั้งเป็นเอกสารใหม่แยกกัน</p>
    <div class="modal-actions">
      <button class="btn" id="dupCancel">ยกเลิก</button>
      <button class="btn btn-primary" id="dupAdd">เพิ่มซ้ำ</button>
    </div>
  `;
  modalBackdrop.classList.add("open");
  modalBox.querySelector("#dupCancel").addEventListener("click", () => modalBackdrop.classList.remove("open"));
  modalBox.querySelector("#dupAdd").addEventListener("click", async () => {
    modalBackdrop.classList.remove("open");
    await api.uploadDocument(file, true);
    await store.refreshAll();
  });
}

document.addEventListener("show-confirm", () => {
  const cfg = store.state.confirmDialog;
  if (!cfg) return;
  modalBox.innerHTML = `
    <h3>${cfg.title}</h3>
    <p>${cfg.message}</p>
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

document.getElementById("addFilesBtn").addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", (e) => { uploadFiles(e.target.files); fileInput.value = ""; });

// Drag & drop anywhere on the app
let dragDepth = 0;
window.addEventListener("dragenter", (e) => {
  if (!e.dataTransfer?.types?.includes("Files")) return;
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
  if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files);
});

document.getElementById("exportBtn").addEventListener("click", () => {
  window.location.href = api.exportUrl();
});

// Global search: routes to Products view: the view itself reads
// state.searchQuery as its initial filter value (see views/products.js) -
// state is the single source of truth here, not a simulated DOM event
// crossing a re-render boundary.
let searchDebounce = null;
document.getElementById("globalSearch").addEventListener("input", (e) => {
  clearTimeout(searchDebounce);
  const val = e.target.value;
  searchDebounce = setTimeout(() => {
    store.navigate("products", { deptFilter: null, searchQuery: val });
  }, 200);
});

// ---------- Polling ----------
async function pollLoop() {
  if (store.hasProcessing() || store.state.documents.length === 0) {
    await store.refreshAll();
  } else {
    await store.refreshDocuments();
  }
  setTimeout(pollLoop, store.hasProcessing() ? 1500 : 5000);
}

store.subscribe(render);

(async function init() {
  await store.refreshAll();
  pollLoop();
})();
