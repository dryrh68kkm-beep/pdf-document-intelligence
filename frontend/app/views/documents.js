import { api } from "../api.js";

let searchQuery = "";
let statusFilter = "all";
let sortMode = "newest";

function qualityLabel(band) {
  return {
    VERIFIED: "เชื่อถือได้",
    GOOD: "คุณภาพดี",
    NEED_REVIEW: "ควรตรวจสอบ",
    HIGH_RISK: "ความเสี่ยงสูง",
  }[band] || "ยังไม่มีคะแนน";
}

function fmtDate(value) {
  if (!value) return "ไม่พบวันที่เอกสาร";
  return new Date(`${value}T00:00:00`).toLocaleDateString("th-TH", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function filteredDocuments(documents) {
  const q = searchQuery.trim().toLowerCase();
  const filtered = documents.filter((doc) => {
    const haystack = [doc.filename, doc.documentDate, doc.documentType, doc.qualityBand]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    const matchesSearch = !q || haystack.includes(q);
    const matchesStatus =
      statusFilter === "all" ||
      (statusFilter === "review" && (doc.qualityCounts?.needReview ?? 0) > 0) ||
      (statusFilter === "error" && doc.status === "error") ||
      (statusFilter === "complete" && doc.status === "complete" && (doc.qualityCounts?.needReview ?? 0) === 0) ||
      doc.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  return filtered.sort((a, b) => {
    if (sortMode === "oldest") return String(a.documentDate || "9999").localeCompare(String(b.documentDate || "9999"));
    if (sortMode === "quality-low") return (a.qualityScore ?? 101) - (b.qualityScore ?? 101);
    if (sortMode === "quality-high") return (b.qualityScore ?? -1) - (a.qualityScore ?? -1);
    return String(b.documentDate || "").localeCompare(String(a.documentDate || ""));
  });
}

export function renderDocuments(container, store) {
  const { documents } = store.state;
  const visible = filteredDocuments(documents);

  container.innerHTML = `
    <div class="workspace-header">
      <div>
        <div class="workspace-title">Documents</div>
        <div class="workspace-sub">แสดง ${visible.length} จาก ${documents.length} ไฟล์</div>
      </div>
    </div>
    <div class="filter-bar" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">
      <input class="search-input" id="docSearch" type="search" placeholder="ค้นหาชื่อไฟล์ / วันที่ / ประเภท" value="${searchQuery}">
      <select class="filter-select" id="docStatusFilter">
        <option value="all"${statusFilter === "all" ? " selected" : ""}>ทุกสถานะ</option>
        <option value="complete"${statusFilter === "complete" ? " selected" : ""}>พร้อมใช้งาน</option>
        <option value="review"${statusFilter === "review" ? " selected" : ""}>ต้องตรวจสอบ</option>
        <option value="processing"${statusFilter === "processing" ? " selected" : ""}>กำลังประมวลผล</option>
        <option value="error"${statusFilter === "error" ? " selected" : ""}>ผิดพลาด</option>
      </select>
      <select class="filter-select" id="docSort">
        <option value="newest"${sortMode === "newest" ? " selected" : ""}>วันที่ใหม่สุด</option>
        <option value="oldest"${sortMode === "oldest" ? " selected" : ""}>วันที่เก่าสุด</option>
        <option value="quality-low"${sortMode === "quality-low" ? " selected" : ""}>Quality ต่ำสุด</option>
        <option value="quality-high"${sortMode === "quality-high" ? " selected" : ""}>Quality สูงสุด</option>
      </select>
    </div>
    <div id="docList"></div>
  `;

  container.querySelector("#docSearch").addEventListener("input", (event) => {
    searchQuery = event.target.value;
    renderDocuments(container, store);
    const input = container.querySelector("#docSearch");
    input?.focus();
    input?.setSelectionRange(searchQuery.length, searchQuery.length);
  });
  container.querySelector("#docStatusFilter").addEventListener("change", (event) => {
    statusFilter = event.target.value;
    renderDocuments(container, store);
  });
  container.querySelector("#docSort").addEventListener("change", (event) => {
    sortMode = event.target.value;
    renderDocuments(container, store);
  });

  const list = container.querySelector("#docList");
  if (!documents.length) {
    list.innerHTML = `<div class="empty-state"><div class="icon">📄</div><div class="title">ยังไม่มีเอกสาร</div></div>`;
    return;
  }
  if (!visible.length) {
    list.innerHTML = `<div class="empty-state"><div class="icon">🔎</div><div class="title">ไม่พบเอกสารที่ตรงกับตัวกรอง</div></div>`;
    return;
  }

  visible.forEach((doc) => {
    const row = document.createElement("div");
    row.className = "doc-row";
    const reviewCount = doc.qualityCounts?.needReview ?? 0;
    const errorCount = doc.qualityCounts?.errors ?? 0;
    const qualityText = doc.qualityScore == null
      ? "Quality —"
      : `Quality ${doc.qualityScore}/100 · ${qualityLabel(doc.qualityBand)}`;
    const statusText =
      doc.status === "complete"
        ? `${fmtDate(doc.documentDate)} · ${doc.rowCount ?? 0} rows · ${doc.pages ?? "?"} pages · ${qualityText}${reviewCount ? ` · ${reviewCount} ต้องตรวจ` : ""}${errorCount ? ` · ${errorCount} error` : ""}`
        : doc.status === "error"
        ? `อ่านไม่สำเร็จ: ${doc.error || "unknown error"}`
        : `${doc.progress?.stage || "กำลังประมวลผล"} ${doc.progress?.total ? `(${doc.progress.current}/${doc.progress.total})` : ""}`;

    row.innerHTML = `
      <span class="status-dot ${doc.status}"></span>
      <div style="min-width:0;flex:1;">
        <div class="doc-name">${doc.filename}</div>
        <div class="doc-meta">${statusText}</div>
      </div>
      <div class="doc-actions">
        ${reviewCount > 0 ? `<button class="btn btn-sm btn-primary" data-action="review">Review ${reviewCount}</button>` : ""}
        ${doc.status !== "processing" ? `<button class="btn btn-sm" data-action="reprocess">Reprocess</button>` : ""}
        <button class="btn btn-sm" data-action="remove">Remove</button>
      </div>
    `;

    row.querySelector('[data-action="review"]')?.addEventListener("click", () => {
      store.selectDashboardDocument(doc.id).then(() => store.navigate("review"));
    });
    row.querySelector('[data-action="reprocess"]')?.addEventListener("click", async () => {
      await api.reprocessDocument(doc.id);
      await store.refreshAll();
    });
    row.querySelector('[data-action="remove"]').addEventListener("click", () => {
      store.set({
        confirmDialog: {
          title: `ลบ ${doc.filename}?`,
          message: "ข้อมูลของไฟล์นี้จะถูกลบออกจาก Dashboard และคำนวณยอดใหม่ทันที",
          onConfirm: async () => {
            await api.deleteDocument(doc.id);
            await store.refreshAll();
          },
        },
      });
      document.dispatchEvent(new CustomEvent("show-confirm"));
    });
    list.appendChild(row);
  });
}
