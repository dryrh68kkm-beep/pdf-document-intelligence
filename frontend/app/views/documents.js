import { api } from "../api.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";
import { escapeHtml } from "../escape.js";
import { icons } from "../icons.js";
import { openPdfModal } from "../pdfViewer.js";

let searchQuery = "";
let statusFilter = "all";
let sortMode = "newest";
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];

const DOCUMENT_TYPE_LABEL = {
  packing_list_bigc_cdc: "Big C",
  packing_list_bpdc: "BPDC",
  UNKNOWN_LAYOUT: "ไม่ทราบ",
};

function qualityLabel(band) {
  return {
    VERIFIED: "เชื่อถือได้",
    GOOD: "คุณภาพดี",
    NEED_REVIEW: "ควรตรวจสอบ",
    HIGH_RISK: "ความเสี่ยงสูง",
  }[band] || "ยังไม่มีคะแนน";
}

function bandChipClass(band) {
  if (band === "VERIFIED" || band === "GOOD") return "HIGH";
  if (band === "NEED_REVIEW") return "MEDIUM";
  if (band === "HIGH_RISK") return "LOW";
  return "MEDIUM";
}

function typeTagClass(documentType) {
  if (documentType === "packing_list_bigc_cdc") return "type-tag-bigc";
  if (documentType === "packing_list_bpdc") return "type-tag-bpdc";
  return "type-tag-unknown";
}

function fmtDate(value) {
  if (!value) return "ไม่พบวันที่เอกสาร";
  return new Date(`${value}T00:00:00`).toLocaleDateString("th-TH", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function fmtDateTime(value) {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" });
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

function isProblemDocument(doc) {
  return doc.qualityBand === "HIGH_RISK" || (doc.qualityCounts?.errors ?? 0) > 0 || doc.status === "error";
}

export function renderDocuments(container, store) {
  const allDocuments = store.state.documents;
  const documents = store.getDateScopedDocuments();
  const visible = filteredDocuments(documents);

  container.innerHTML = `
    <div class="workspace-header">
      <div>
        <div class="workspace-title">Documents</div>
        <div class="workspace-sub">แสดง ${visible.length} จาก ${documents.length} ไฟล์ในช่วงวันที่ที่เลือก${documents.length !== allDocuments.length ? ` · ทั้งหมด ${allDocuments.length} ไฟล์` : ""}</div>
      </div>
    </div>
    <div class="filter-bar" style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px;">
      <input class="search-input" id="docSearch" type="search" placeholder="ค้นหาชื่อไฟล์ / วันที่ / ประเภท" value="${escapeHtml(searchQuery)}">
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
    page = 1;
    renderDocuments(container, store);
    const input = container.querySelector("#docSearch");
    input?.focus();
    input?.setSelectionRange(searchQuery.length, searchQuery.length);
  });
  container.querySelector("#docStatusFilter").addEventListener("change", (event) => {
    statusFilter = event.target.value;
    page = 1;
    renderDocuments(container, store);
  });
  container.querySelector("#docSort").addEventListener("change", (event) => {
    sortMode = event.target.value;
    page = 1;
    renderDocuments(container, store);
  });

  const list = container.querySelector("#docList");
  if (!documents.length) {
    list.innerHTML = `<div class="empty-state"><div class="icon">📄</div><div class="title">ยังไม่มีเอกสาร</div><div>เพิ่ม PDF เพื่อเริ่มวิเคราะห์</div></div>`;
    return;
  }
  if (!visible.length) {
    list.innerHTML = `<div class="empty-state"><div class="icon">🔎</div><div class="title">ไม่พบเอกสารที่ตรงกับตัวกรอง</div></div>`;
    return;
  }

  const { pageRows, total } = paginate(visible, page, pageSize);

  const wrap = document.createElement("div");
  wrap.className = "doc-table-wrap";
  const table = document.createElement("table");
  table.className = "doc-table";
  table.innerHTML = `
    <thead>
      <tr>
        <th>ไฟล์</th>
        <th>ประเภท</th>
        <th>วันที่เอกสาร</th>
        <th class="num">หน้า</th>
        <th class="num">รายการ</th>
        <th>คุณภาพ</th>
        <th class="num">ต้องตรวจสอบ</th>
        <th>สถานะ</th>
        <th>นำเข้าเมื่อ</th>
        <th></th>
      </tr>
    </thead>
    <tbody></tbody>
  `;
  wrap.appendChild(table);
  list.innerHTML = "";
  list.appendChild(wrap);
  const paginationHost = document.createElement("div");
  list.appendChild(paginationHost);
  renderPaginationBar(paginationHost, {
    page,
    pageSize,
    total,
    onPageChange: (p) => { page = p; renderDocuments(container, store); },
    onPageSizeChange: (size) => { pageSize = size; page = 1; renderDocuments(container, store); },
  });

  const tbody = table.querySelector("tbody");
  pageRows.forEach((doc) => {
    const reviewCount = doc.qualityCounts?.needReview ?? 0;
    const problem = isProblemDocument(doc);
    const statusLabel = doc.status === "complete" ? "พร้อมใช้งาน" : doc.status === "error" ? "ผิดพลาด" : "กำลังประมวลผล";
    const tr = document.createElement("tr");
    tr.className = problem ? "doc-table-row problem" : "doc-table-row";
    tr.innerHTML = `
      <td>
        <div style="display:flex;align-items:center;gap:8px;">
          <span class="status-dot ${doc.status}"></span>
          <span class="doc-name">${escapeHtml(doc.filename)}</span>
          <button type="button" class="icon-btn-sm" data-action="view-pdf" title="ดู PDF ต้นฉบับ" aria-label="ดู PDF ต้นฉบับ">${icons.eye}</button>
        </div>
        ${doc.status === "error" ? `<div class="doc-meta">${escapeHtml(doc.error) || "unknown error"}</div>` : doc.status === "processing" ? `<div class="doc-meta">${escapeHtml(doc.progress?.stage) || "กำลังประมวลผล"} ${doc.progress?.total ? `(${doc.progress.current}/${doc.progress.total})` : ""}</div>` : ""}
      </td>
      <td><span class="type-tag ${typeTagClass(doc.documentType)}">${DOCUMENT_TYPE_LABEL[doc.documentType] || "ไม่ทราบ"}</span></td>
      <td>${fmtDate(doc.documentDate)}</td>
      <td class="num mono">${doc.pages ?? "—"}</td>
      <td class="num mono">${doc.rowCount ?? "—"}</td>
      <td>${doc.qualityScore == null ? "—" : `<span class="band-chip band-${bandChipClass(doc.qualityBand)}"><span class="dot"></span>${doc.qualityScore}/100 · ${qualityLabel(doc.qualityBand)}</span>`}</td>
      <td class="num mono">${reviewCount || "—"}</td>
      <td><span class="status-pill status-${doc.status}">${statusLabel}</span></td>
      <td class="mono">${fmtDateTime(doc.uploadedAt)}</td>
      <td class="doc-table-actions">
        ${reviewCount > 0 ? `<button class="btn btn-sm btn-primary" data-action="review">Review ${reviewCount}</button>` : ""}
        ${doc.status !== "processing" ? `<button class="btn btn-sm" data-action="reprocess">Reprocess</button>` : ""}
        <button class="btn btn-sm" data-action="remove"${doc.status === "processing" ? ` disabled title="ไม่สามารถลบเอกสารที่กำลังประมวลผลอยู่ได้"` : ""}>Remove</button>
      </td>
    `;

    // Real gap found during a Documents UX audit (PR18): there was no way
    // at all to view the original PDF from the Documents page - only
    // reachable indirectly, per product row, via the detail panel's own
    // "ดูจากเอกสารต้นฉบับ" link (detailPanel.js), which needs a completed,
    // reconciled row to exist first. The file is on disk from the moment
    // it's uploaded (api/app.py moves it into place before any processing
    // job is even submitted - PR5), so this works for every status.
    tr.querySelector('[data-action="view-pdf"]')?.addEventListener("click", (e) => {
      e.stopPropagation();
      openPdfModal(doc.id, { title: doc.filename });
    });

    tr.querySelector('[data-action="review"]')?.addEventListener("click", () => {
      store.selectDashboardDocument(doc.id).then(() => store.navigate("review"));
    });
    const doReprocess = async () => {
      const btn = tr.querySelector('[data-action="reprocess"]');
      // The server call + refreshAll() round-trip isn't instant - without
      // this, clicking Reprocess looked like nothing happened until the
      // next render, which is exactly the "did it even start?" complaint
      // this button used to get.
      if (btn) {
        btn.disabled = true;
        btn.textContent = "กำลังเริ่ม...";
      }
      try {
        await api.reprocessDocument(doc.id);
        await store.refreshAll();
      } catch (error) {
        store.set({
          errorDialog: {
            title: "ประมวลผลใหม่ไม่สำเร็จ",
            message: String(error?.message || error),
            diagnosticId: error?.diagnosticId,
            onRetry: doReprocess,
          },
        });
        document.dispatchEvent(new CustomEvent("show-error"));
        if (btn) {
          btn.disabled = false;
          btn.textContent = "Reprocess";
        }
      }
    };
    tr.querySelector('[data-action="reprocess"]')?.addEventListener("click", doReprocess);
    tr.querySelector('[data-action="remove"]').addEventListener("click", () => {
      store.set({
        confirmDialog: {
          title: `ลบ ${doc.filename}?`,
          message: "ข้อมูลของไฟล์นี้จะถูกลบออกจาก Dashboard และคำนวณยอดใหม่ทันที",
          onConfirm: async () => {
            try {
              await api.deleteDocument(doc.id);
              await store.refreshAll();
            } catch (error) {
              store.set({
                errorDialog: {
                  title: "ลบไม่สำเร็จ",
                  message: String(error?.message || error),
                  diagnosticId: error?.diagnosticId,
                },
              });
              document.dispatchEvent(new CustomEvent("show-error"));
            }
          },
        },
      });
      document.dispatchEvent(new CustomEvent("show-confirm"));
    });
    tbody.appendChild(tr);
  });
}
