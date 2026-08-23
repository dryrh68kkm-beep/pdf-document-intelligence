import { renderProductTable } from "../components/productTable.js";

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
// lower-severity evidence-only flag with otherwise-usable data (labeled
// "Resolved" per spec - i.e. low risk / ready to confirm with "Mark
// Resolved" rather than requiring a correction first).
const TIERS = [
  { key: "high", label: "High Risk", sub: "ต้องแก้ไขก่อนใช้ข้อมูลได้ (รหัสสินค้า/แผนกขัดแย้ง)", tone: "critical", test: (p) => p._reviewPriority === 0 },
  { key: "needs", label: "Needs Review", sub: "ตรวจสอบยอด/จำนวนที่ไม่ตรงกัน", tone: "warning", test: (p) => p._reviewPriority === 1 || p._reviewPriority === 2 },
  { key: "resolved", label: "Resolved", sub: "ความเสี่ยงต่ำ ข้อมูลใช้ได้ - ตรวจหลักฐานแล้วกด \"ยืนยันว่าถูกต้อง\"", tone: "success", test: (p) => p._reviewPriority >= 3 },
];

let cachedProductsRef = null;
let cachedItems = [];
let cachedCounts = { critical: 0, numeric: 0, evidence: 0 };
const scrollTops = {};

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

function fmtPct(value) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

function buildEvidenceDetail(product) {
  const issues = product._fieldIssues?.length ? product._fieldIssues : fieldIssues(product);
  const primaryFieldName = issues[0]?.field || "name";
  const fv = product.fields?.[primaryFieldName];
  return { primaryFieldName, fv, issues };
}

export function renderReview(container, store) {
  const { products, panel } = store.state;
  const { items, counts } = derivedReviewItems(products);

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Review Queue</div>
      <div class="workspace-sub">${items.length.toLocaleString()} รายการต้องตรวจสอบ — เรียงจากความเสี่ยงสูงสุดก่อน</div>
    </div>
    ${items.length === 0
      ? `<div class="empty-state"><div class="icon">✅</div><div class="title">ไม่มีรายการต้องตรวจสอบ</div></div>`
      : `
        <div class="review-count-chips">
          <span class="review-count-chip tone-critical"><span class="dot"></span>High Risk ${counts.critical.toLocaleString()}</span>
          <span class="review-count-chip tone-warning"><span class="dot"></span>Needs Review ${counts.numeric.toLocaleString()}</span>
          <span class="review-count-chip tone-success"><span class="dot"></span>Resolved ${counts.evidence.toLocaleString()}</span>
        </div>
        <div id="reviewTiers"></div>`}
  `;

  if (!items.length) return;

  const tiersHost = container.querySelector("#reviewTiers");

  TIERS.forEach((tier) => {
    const rows = items.filter(tier.test);
    if (!rows.length) return;

    const section = document.createElement("section");
    section.className = "review-tier";
    section.innerHTML = `
      <div class="review-tier-head tone-${tier.tone}">
        <span class="review-tier-title">${tier.label}</span>
        <span class="review-tier-count">${rows.length.toLocaleString()} รายการ</span>
      </div>
      <div class="workspace-sub" style="margin:6px 0 10px;">${tier.sub}</div>
      <div class="review-tier-reason" id="reason-${tier.key}">เลือกแถวเพื่อดูสาเหตุ, field, หน้า PDF และหลักฐานต้นฉบับ</div>
      <div class="review-tier-table" id="table-${tier.key}"></div>
    `;
    tiersHost.appendChild(section);

    const reasonHost = section.querySelector(`#reason-${tier.key}`);
    const showReason = (row) => {
      const { primaryFieldName, fv } = buildEvidenceDetail(row);
      const issueFields = row._fieldIssues?.length
        ? [...new Set(row._fieldIssues.map((x) => x.field))].join(", ")
        : primaryFieldName;
      reasonHost.innerHTML = `
        <div class="review-detail-grid">
          <div><span class="dp-label">สินค้า</span><div class="dp-value">${row.fields?.name?.value ?? "—"}</div></div>
          <div><span class="dp-label">Article</span><div class="dp-value mono">${row.fields?.article?.value ?? "—"}</div></div>
          <div><span class="dp-label">Barcode</span><div class="dp-value mono">${row.fields?.barcode?.value ?? "—"}</div></div>
          <div><span class="dp-label">Field ที่มีปัญหา</span><div class="dp-value">${issueFields}</div></div>
          <div><span class="dp-label">ค่า OCR อ่านได้</span><div class="dp-value">${fv?.ocrRaw ?? "—"}</div></div>
          <div><span class="dp-label">ค่าปัจจุบัน (Master/PDF)</span><div class="dp-value">${fv?.value ?? "—"}</div></div>
          <div><span class="dp-label">ความมั่นใจ</span><div class="dp-value mono">${fmtPct(fv?.ocrConfidence ?? fv?.confidence)}</div></div>
          <div><span class="dp-label">หน้า PDF</span><div class="dp-value mono">${row.page ?? "—"}</div></div>
        </div>
        <div class="dp-source-note" style="margin-top:6px;">เหตุผล: ${reasonText(row)}</div>
      `;
    };

    renderProductTable(section.querySelector(`#table-${tier.key}`), rows, {
      selectedRowId: panel?.rowId,
      initialScrollTop: scrollTops[tier.key] || 0,
      onRowClick: (row) => {
        showReason(row);
        store.openPanel({ type: "product", rowId: row.rowId, data: row });
      },
    });

    const bodyEl = section.querySelector(".vtable-body");
    bodyEl?.addEventListener("scroll", () => { scrollTops[tier.key] = bodyEl.scrollTop; });

    const selected = rows.find((p) => p.rowId === panel?.rowId);
    if (selected) showReason(selected);
  });
}
