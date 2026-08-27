// Division -> Department drill-down.
// Two entry points reuse this one view:
//   Dashboard -> one document's Division summary
//   Departments -> all active data aggregated by Division
// Both end at the existing Products view so Product Detail/Evidence remains
// a single implementation.
import { escapeHtml } from "../escape.js";

function fmtNum(n) {
  return (n ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

function fmtBaht(n) {
  return "฿" + (n ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const DOCUMENT_SORTS = {
  sku: (a, b) => (b.skuQty || 0) - (a.skuQty || 0),
  weight: (a, b) => (b.weight || 0) - (a.weight || 0),
  pu: (a, b) => (b.puQty || 0) - (a.puQty || 0),
  rows: (a, b) => (b.rowCount || 0) - (a.rowCount || 0),
};
const DOCUMENT_SORT_LABELS = { sku: "SKU", weight: "Weight", pu: "PU", rows: "Rows" };

const AGGREGATE_SORTS = {
  amount: (a, b) => (b.amount || 0) - (a.amount || 0),
  sku: (a, b) => (b.skuCount || 0) - (a.skuCount || 0),
  rows: (a, b) => (b.rowCount || 0) - (a.rowCount || 0),
  review: (a, b) => (b.reviewCount || 0) - (a.reviewCount || 0),
  name: (a, b) => a.name.localeCompare(b.name, "th"),
};
const AGGREGATE_SORT_LABELS = {
  amount: "มูลค่า",
  sku: "SKU",
  rows: "รายการ",
  review: "ต้องตรวจสอบ",
  name: "ชื่อ",
};

let currentSort = "sku";

function documentDeptRow(d, store, hasAmountData) {
  const row = document.createElement("div");
  row.className = "dept-card";
  row.innerHTML = `
    <div class="dept-card-head">
      <span class="dept-card-name">${escapeHtml(d.name)}</span>
      ${d.reviewCount > 0 ? `<span class="dept-card-badge warn">${d.reviewCount} ต้องตรวจสอบ</span>` : `<span class="dept-card-badge">✓</span>`}
    </div>
    <div class="dept-card-stat">${d.rowCount} รายการ${hasAmountData ? ` · ${fmtBaht(d.amount)}` : ""}</div>
    <div class="dept-card-stat">น้ำหนัก ${fmtNum(d.weight)} กก. · PU ${fmtNum(d.puQty)} · SKU ${fmtNum(d.skuQty)}</div>
  `;
  row.addEventListener("click", () => store.navigate("products", { deptFilter: d.name, deptFilterLabel: null }));
  return row;
}

function aggregateDeptRow(d, store, divisionHasAmountData) {
  const row = document.createElement("div");
  row.className = "dept-card dept-card-simple";
  const value = divisionHasAmountData
    ? (d.amountAvailable ? fmtBaht(d.amount) : "—")
    : `${fmtNum(d.skuCount)} SKU`;
  const valueLabel = divisionHasAmountData ? "มูลค่า" : "จำนวน SKU";
  row.innerHTML = `
    <div class="dept-card-head">
      <span class="dept-card-name">${escapeHtml(d.name)}</span>
      <span class="dept-card-arrow" aria-hidden="true">›</span>
    </div>
    <div class="dept-card-value mono">${value}</div>
    <div class="dept-card-value-label">${valueLabel}</div>
    <div class="dept-card-stat">${fmtNum(d.skuCount)} SKU · ${fmtNum(d.rowCount)} รายการ</div>
    ${d.reviewCount > 0 ? `<div class="dept-card-review"><span class="dept-card-badge warn">${fmtNum(d.reviewCount)} ต้องตรวจสอบ</span></div>` : ""}
  `;
  // deptFilterLabel must be cleared explicitly - store.navigate() only
  // overwrites supplied keys, so a stale Division label from a previous
  // Dashboard click must never become this Department's Products title.
  row.addEventListener("click", () => store.navigate("products", { deptFilter: d.name, deptFilterLabel: null }));
  return row;
}

export function renderDivisionDetail(container, store) {
  const { divisionDetail, divisionSummary } = store.state;
  if (!divisionDetail) {
    store.navigate("dashboard");
    return;
  }

  const fromDepartments = divisionDetail.source === "departments";
  const summaryEntry = fromDepartments
    ? null
    : (divisionSummary?.divisions || []).find((d) => d.divisionCode === divisionDetail.divisionCode);

  const hasAmountData = fromDepartments
    ? Boolean(divisionDetail.amountAvailable)
    : Boolean(divisionSummary?.amountAvailable);

  const aggregateSummary = divisionDetail.summary || null;
  const summaryMarkup = fromDepartments && aggregateSummary
    ? `
      <div class="division-detail-summary">
        <span><b>${fmtNum(aggregateSummary.departmentCount)}</b> แผนก</span>
        <span><b>${fmtNum(aggregateSummary.skuCount)}</b> SKU</span>
        <span><b>${fmtNum(aggregateSummary.rowCount)}</b> รายการ</span>
        ${hasAmountData ? `<span class="division-detail-summary-value"><b>${fmtBaht(aggregateSummary.amount)}</b> มูลค่ารวม</span>` : ""}
        ${aggregateSummary.reviewCount > 0 ? `<span class="dept-card-badge warn">${fmtNum(aggregateSummary.reviewCount)} ต้องตรวจสอบ</span>` : ""}
      </div>`
    : "";

  // Preserve the existing document-scoped KPI block for Dashboard entry.
  const documentKpis = !fromDepartments && summaryEntry
    ? `
      <div class="kpi-row">
        <div class="kpi-card"><div class="kpi-value">${fmtNum(summaryEntry.rowCount)}</div><div class="kpi-label">รายการ</div></div>
        <div class="kpi-card"><div class="kpi-value">${fmtNum(summaryEntry.weight)}</div><div class="kpi-label">น้ำหนัก (กก.)</div></div>
        <div class="kpi-card"><div class="kpi-value">${fmtNum(summaryEntry.puQty)}</div><div class="kpi-label">PU</div></div>
        <div class="kpi-card"><div class="kpi-value">${fmtNum(summaryEntry.skuQty)}</div><div class="kpi-label">SKU</div></div>
        ${hasAmountData ? `<div class="kpi-card"><div class="kpi-value">${fmtBaht(summaryEntry.amount)}</div><div class="kpi-label">มูลค่ารวม (฿)</div></div>` : ""}
      </div>`
    : "";

  const sorts = fromDepartments ? AGGREGATE_SORTS : DOCUMENT_SORTS;
  const sortLabels = fromDepartments ? AGGREGATE_SORT_LABELS : DOCUMENT_SORT_LABELS;
  const defaultSort = fromDepartments && hasAmountData ? "amount" : "sku";
  const activeSort = sorts[currentSort] ? currentSort : defaultSort;
  if (!sorts[currentSort]) currentSort = activeSort;

  const backLabel = fromDepartments ? "‹ กลับไปหน้า Departments" : "‹ กลับไปหน้า Dashboard";
  const subtitle = fromDepartments
    ? `Division ${escapeHtml(divisionDetail.divisionCode)} · ${fmtNum(divisionDetail.departments.length)} แผนก`
    : `${fmtNum(divisionDetail.departments.length)} แผนก`;

  container.innerHTML = `
    <div class="back-link" id="backToParent">${backLabel}</div>
    <div class="workspace-header">
      <div class="workspace-title">${fromDepartments ? escapeHtml(divisionDetail.divisionName) : `${escapeHtml(divisionDetail.divisionCode)} ${escapeHtml(divisionDetail.divisionName)}`}</div>
      <div class="workspace-sub">${subtitle}</div>
    </div>
    ${summaryMarkup}
    ${documentKpis}
    <div class="section-title">
      แผนก
      <span class="sort-controls">
        เรียงตาม:
        ${Object.entries(sortLabels)
          .filter(([key]) => !(key === "amount" && !hasAmountData))
          .map(([key, label]) => `<button class="sort-btn${key === activeSort ? " active" : ""}" data-sort="${key}">${label}</button>`)
          .join("")}
      </span>
    </div>
    <div class="dept-grid" id="deptGrid"></div>
  `;

  container.querySelector("#backToParent").addEventListener("click", () => {
    store.navigate(fromDepartments ? "departments" : "dashboard", { divisionDetail: null });
  });

  container.querySelectorAll(".sort-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentSort = btn.dataset.sort;
      renderDivisionDetail(container, store);
    });
  });

  const grid = container.querySelector("#deptGrid");
  const sorter = sorts[currentSort] || sorts[defaultSort];
  const sorted = [...divisionDetail.departments].sort(sorter);
  sorted.forEach((d) => {
    grid.appendChild(
      fromDepartments
        ? aggregateDeptRow(d, store, hasAmountData)
        : documentDeptRow(d, store, hasAmountData)
    );
  });
}
