import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";
import { icons } from "../icons.js";

const REASON_LABELS = {
  INVALID_IDENTIFIER: "รหัสสินค้าไม่ถูกต้อง",
  INVALID_ARTICLE_FORMAT: "รูปแบบ Article ไม่ถูกต้อง",
  INVALID_BARCODE_FORMAT: "รูปแบบ Barcode ไม่ถูกต้อง",
  UNKNOWN_BARCODE: "ไม่พบ Barcode ใน Master",
  DEPARTMENT_CONFLICT: "Department ขัดแย้ง",
  AMOUNT_MISMATCH: "ยอดรวมไม่ตรง",
  MISSING_QUANTITY: "จำนวนหาย",
  MISSING_AMOUNT: "มูลค่าหาย",
  OCR_CONFLICT: "OCR อ่านไม่ตรงกับข้อความ PDF",
  SOURCE_CONFLICT: "ข้อมูลจากแหล่งอ่านไม่ตรงกัน",
  MISSING_DEPARTMENT: "ไม่พบ Department",
  CATALOG_CHECKED_NOT_FOUND: "ตรวจสอบกับ Official Master แล้ว - ไม่พบ Barcode",
};

const REASON_PRIORITY = {
  INVALID_IDENTIFIER: 0,
  INVALID_ARTICLE_FORMAT: 0,
  INVALID_BARCODE_FORMAT: 0,
  UNKNOWN_BARCODE: 0,
  DEPARTMENT_CONFLICT: 0,
  AMOUNT_MISMATCH: 1,
  MISSING_QUANTITY: 2,
  MISSING_AMOUNT: 2,
  OCR_CONFLICT: 3,
  SOURCE_CONFLICT: 3,
  MISSING_DEPARTMENT: 3,
};

// Risk tiers (Phase 5): priority 0 is a hard identifier/department conflict
// (High Risk), 1-2 is a numeric reconciliation gap (Needs Review), 3+ is a
// lower-severity evidence-only flag with otherwise-usable data - ready to
// confirm with "Mark Resolved" (see detailPanel.js), but NOT resolved yet:
// every row here still has reviewRequired=true, since a row that's actually
// been confirmed leaves this list entirely. Labeling this tier "Resolved"
// would claim work that hasn't happened - "Low Priority" says what's true.
const TABS = [
  { key: "all", label: "ทั้งหมด", tone: "neutral", test: () => true },
  { key: "high", label: "High Risk", tone: "critical", test: (p) => p._reviewPriority === 0 },
  { key: "needs", label: "Needs Review", tone: "warning", test: (p) => p._reviewPriority === 1 || p._reviewPriority === 2 },
  { key: "low", label: "Low Priority", tone: "success", test: (p) => p._reviewPriority >= 3 },
];

const PRIORITY_PILL = {
  0: `<span class="pill pill-critical">High</span>`,
  1: `<span class="pill pill-warning">Medium</span>`,
  2: `<span class="pill pill-warning">Medium</span>`,
  3: `<span class="pill pill-accent">Low</span>`,
};

let cachedProductsRef = null;
let cachedItems = [];
let cachedCounts = { critical: 0, numeric: 0, evidence: 0 };

let activeTab = "all";
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];

function fieldIssues(product) {
  const issues = [];
  for (const [field, value] of Object.entries(product.fields || {})) {
    for (const flag of value?.flags || []) {
      if (flag === "CATALOG_MATCH" || flag === "CATALOG_NAME_MISMATCH") continue;
      issues.push({ field, flag, page: value?.page ?? product.page });
    }
  }
  return issues;
}

function priorityFromIssues(product, issues) {
  const reasons = [...(product.reviewReasons || []), ...issues.map((x) => x.flag)];
  return Math.min(...reasons.map((r) => REASON_PRIORITY[r] ?? 4), 4);
}

function derivedReviewItems(products) {
  if (products === cachedProductsRef) return { items: cachedItems, counts: cachedCounts };

  cachedProductsRef = products;
  cachedItems = products
    .filter((p) => p.reviewRequired)
    .map((p) => {
      const issues = fieldIssues(p);
      return { ...p, _reviewPriority: priorityFromIssues(p, issues), _fieldIssues: issues };
    })
    .sort((a, b) => a._reviewPriority - b._reviewPriority || (a.page || 0) - (b.page || 0));

  cachedCounts = {
    critical: cachedItems.filter((p) => p._reviewPriority === 0).length,
    numeric: cachedItems.filter((p) => p._reviewPriority === 1 || p._reviewPriority === 2).length,
    evidence: cachedItems.filter((p) => p._reviewPriority >= 3).length,
  };
  return { items: cachedItems, counts: cachedCounts };
}

function reasonText(product) {
  const issues = product._fieldIssues || fieldIssues(product);
  const reasons = [...new Set([...(product.reviewReasons || []), ...issues.map((x) => x.flag)])];
  if (!reasons.length) return "ต้องตรวจสอบความถูกต้อง";
  return reasons.map((r) => REASON_LABELS[r] || r).join(" • ");
}

function fmt(v) {
  if (v === null || v === undefined || v === "") return "—";
  return v;
}

function fmtPct(f) {
  const value = f.barcode?.confidence ?? f.article?.confidence ?? f.name?.confidence;
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

const COLUMNS = [
  { key: "priority", label: "PRIORITY", render: (r) => PRIORITY_PILL[r._reviewPriority] ?? `<span class="pill pill-accent">Low</span>` },
  { key: "article", label: "ARTICLE", render: (r) => `<span class="mono">${fmt(r.fields?.article?.value)}</span>` },
  { key: "barcode", label: "BARCODE", render: (r) => `<span class="mono">${fmt(r.fields?.barcode?.value)}</span>` },
  { key: "name", label: "ชื่อสินค้า", render: (r) => fmt(r.fields?.name?.value) },
  { key: "dept", label: "แผนก", render: (r) => fmt(r.department) },
  { key: "reason", label: "ประเภท", render: (r) => `<span title="${reasonText(r)}">${reasonText(r)}</span>` },
  { key: "confidence", label: "Confidence", align: "num", render: (r) => `<span class="mono">${fmtPct(r.fields || {})}</span>` },
  { key: "status", label: "สถานะ", render: () => `<span class="workspace-sub">รอการตรวจสอบ</span>` },
  {
    key: "actions",
    label: "จัดการ",
    render: () => `<button type="button" class="icon-btn-sm tone-accent" data-row-action="view" aria-label="ดูรายละเอียด">${icons.eye}</button>`,
  },
];

export function renderReview(container, store) {
  const { products, panel } = store.state;
  const { items, counts } = derivedReviewItems(products);

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Review Queue</div>
      <div class="workspace-sub">รายการที่ต้องตรวจสอบ</div>
    </div>
    ${items.length === 0
      ? `<div class="empty-state"><div class="icon">✅</div><div class="title">ไม่มีรายการต้องตรวจสอบ</div></div>`
      : `
        <div class="tab-bar" id="reviewTabs"></div>
        <div class="review-tier-reason" id="reviewReason">เลือกแถวเพื่อดูสาเหตุ, field, หน้า PDF และหลักฐานต้นฉบับ</div>
        <div id="tableHost"></div>
        <div id="paginationHost"></div>`}
  `;

  if (!items.length) return;

  const tabsHost = container.querySelector("#reviewTabs");
  tabsHost.innerHTML = TABS.map((tab) => {
    const count = tab.key === "all" ? items.length : items.filter(tab.test).length;
    return `<button type="button" class="tab-item${activeTab === tab.key ? " active" : ""}" data-tab="${tab.key}">
      ${tab.label} <span class="tab-count tone-${tab.tone}">${count}</span>
    </button>`;
  }).join("");
  tabsHost.querySelectorAll(".tab-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      page = 1;
      renderReview(container, store);
    });
  });

  const host = container.querySelector("#tableHost");
  const paginationHost = container.querySelector("#paginationHost");
  const reasonHost = container.querySelector("#reviewReason");

  const showReason = (row) => {
    const issues = row._fieldIssues?.length ? row._fieldIssues : fieldIssues(row);
    const primaryFieldName = issues[0]?.field || "name";
    const fv = row.fields?.[primaryFieldName];
    const issueFields = issues.length ? [...new Set(issues.map((x) => x.field))].join(", ") : primaryFieldName;
    reasonHost.innerHTML = `
      <div class="review-detail-grid">
        <div><span class="dp-label">สินค้า</span><div class="dp-value">${row.fields?.name?.value ?? "—"}</div></div>
        <div><span class="dp-label">Article</span><div class="dp-value mono">${row.fields?.article?.value ?? "—"}</div></div>
        <div><span class="dp-label">Barcode</span><div class="dp-value mono">${row.fields?.barcode?.value ?? "—"}</div></div>
        <div><span class="dp-label">Field ที่มีปัญหา</span><div class="dp-value">${issueFields}</div></div>
        <div><span class="dp-label">ค่า OCR อ่านได้</span><div class="dp-value">${fv?.ocrRaw ?? "—"}</div></div>
        <div><span class="dp-label">ค่าปัจจุบัน (Master/PDF)</span><div class="dp-value">${fv?.value ?? "—"}</div></div>
        <div><span class="dp-label">ความมั่นใจ</span><div class="dp-value mono">${fv?.ocrConfidence ?? fv?.confidence ? Math.round((fv.ocrConfidence ?? fv.confidence) * 100) + "%" : "—"}</div></div>
        <div><span class="dp-label">หน้า PDF</span><div class="dp-value mono">${row.page ?? "—"}</div></div>
      </div>
      <div class="dp-source-note" style="margin-top:6px;">เหตุผล: ${reasonText(row)}</div>
    `;
  };

  function draw() {
    const tab = TABS.find((t) => t.key === activeTab) || TABS[0];
    const rows = items.filter(tab.test);
    const { pageRows, total } = paginate(rows, page, pageSize);
    renderDataTable(host, pageRows, {
      columns: COLUMNS,
      getRowId: (row) => row.rowId,
      selectedRowId: panel?.rowId,
      onRowClick: (row) => {
        showReason(row);
        store.openPanel({ type: "product", rowId: row.rowId, data: row });
      },
      emptyMessage: "ไม่มีรายการในกลุ่มนี้",
    });
    renderPaginationBar(paginationHost, {
      page,
      pageSize,
      total,
      onPageChange: (p) => { page = p; draw(); },
      onPageSizeChange: (size) => { pageSize = size; page = 1; draw(); },
    });

    const selected = rows.find((p) => p.rowId === panel?.rowId);
    if (selected) showReason(selected);
  }

  draw();
}
