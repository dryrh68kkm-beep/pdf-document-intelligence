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

let cachedProductsRef = null;
let cachedItems = [];
let cachedCounts = { critical: 0, numeric: 0, evidence: 0 };

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

export function renderReview(container, store) {
  const { products, panel } = store.state;
  const { items, counts } = derivedReviewItems(products);
  const scrollTop = container.querySelector(".vtable-body")?.scrollTop || 0;

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Review Queue</div>
      <div class="workspace-sub">${items.length.toLocaleString()} รายการต้องตรวจสอบ — เรียงจากความเสี่ยงสูงสุดก่อน</div>
    </div>
    ${items.length === 0
      ? `<div class="empty-state"><div class="icon">✅</div><div class="title">ไม่มีรายการต้องตรวจสอบ</div></div>`
      : `
        <div class="workspace-sub" style="margin-bottom:10px;">
          สำคัญ ${counts.critical.toLocaleString()} • เกี่ยวกับยอด/จำนวน ${counts.numeric.toLocaleString()} • ตรวจหลักฐาน ${counts.evidence.toLocaleString()}
        </div>
        <div id="reviewReason" class="workspace-sub" style="margin-bottom:12px;">เลือกแถวเพื่อดูสาเหตุ, field, หน้า PDF และหลักฐานต้นฉบับ</div>
        <div id="tableHost"></div>`}
  `;

  if (!items.length) return;

  const showReason = (row) => {
    const issueFields = row._fieldIssues?.length
      ? ` | Field: ${[...new Set(row._fieldIssues.map((x) => x.field))].join(", ")}`
      : "";
    const page = row.page ? ` | หน้า ${row.page}` : "";
    const reason = container.querySelector("#reviewReason");
    if (reason) reason.textContent = `${reasonText(row)}${issueFields}${page}`;
  };

  renderProductTable(container.querySelector("#tableHost"), items, {
    selectedRowId: panel?.rowId,
    initialScrollTop: scrollTop,
    onRowClick: (row) => {
      showReason(row);
      store.openPanel({ type: "product", rowId: row.rowId, data: row });
    },
  });

  const selected = items.find((p) => p.rowId === panel?.rowId);
  if (selected) showReason(selected);
}
