// Division -> Department drill-down (step 2 of the Dashboard hierarchy).
// Clicking a department here hands off to the existing Products view
// (deptFilter) so Product Detail/Evidence stays the one implementation.
import { escapeHtml } from "../escape.js";

function fmtNum(n) {
  return (n ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

function fmtBaht(n) {
  return "฿" + (n ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

const SORTS = {
  sku: (a, b) => b.skuQty - a.skuQty,
  weight: (a, b) => b.weight - a.weight,
  pu: (a, b) => b.puQty - a.puQty,
  rows: (a, b) => b.rowCount - a.rowCount,
};
const SORT_LABELS = { sku: "SKU", weight: "Weight", pu: "PU", rows: "Rows" };

let currentSort = "sku";

function deptRow(d, store, hasAmountData) {
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
  // deptFilterLabel must be cleared explicitly - see the same comment in
  // departments.js's deptCard(): store.navigate() only overwrites the keys
  // it's given, so a stale label from an earlier click elsewhere would
  // otherwise show the wrong name as the Products page title.
  row.addEventListener("click", () => store.navigate("products", { deptFilter: d.name, deptFilterLabel: null }));
  return row;
}

export function renderDivisionDetail(container, store) {
  const { divisionDetail, divisionSummary } = store.state;
  if (!divisionDetail) {
    store.navigate("dashboard");
    return;
  }

  const summaryEntry = (divisionSummary?.divisions || []).find(
    (d) => d.divisionCode === divisionDetail.divisionCode
  );

  const hasAmountData = Boolean(divisionSummary?.amountAvailable);
  const kpis = summaryEntry
    ? `
      <div class="kpi-row">
        <div class="kpi-card"><div class="kpi-value">${fmtNum(summaryEntry.rowCount)}</div><div class="kpi-label">รายการ</div></div>
        <div class="kpi-card"><div class="kpi-value">${fmtNum(summaryEntry.weight)}</div><div class="kpi-label">น้ำหนัก (กก.)</div></div>
        <div class="kpi-card"><div class="kpi-value">${fmtNum(summaryEntry.puQty)}</div><div class="kpi-label">PU</div></div>
        <div class="kpi-card"><div class="kpi-value">${fmtNum(summaryEntry.skuQty)}</div><div class="kpi-label">SKU</div></div>
        ${hasAmountData ? `<div class="kpi-card"><div class="kpi-value">${fmtBaht(summaryEntry.amount)}</div><div class="kpi-label">มูลค่ารวม (฿)</div></div>` : ""}
      </div>`
    : "";

  container.innerHTML = `
    <div class="back-link" id="backToDashboard">‹ กลับไปหน้า Dashboard</div>
    <div class="workspace-header">
      <div class="workspace-title">${escapeHtml(divisionDetail.divisionCode)} ${escapeHtml(divisionDetail.divisionName)}</div>
      <div class="workspace-sub">${divisionDetail.departments.length} แผนก</div>
    </div>
    ${kpis}
    <div class="section-title">
      แผนก
      <span class="sort-controls">
        เรียงตาม:
        ${Object.entries(SORT_LABELS)
          .map(([key, label]) => `<button class="sort-btn${key === currentSort ? " active" : ""}" data-sort="${key}">${label}</button>`)
          .join("")}
      </span>
    </div>
    <div class="dept-grid" id="deptGrid"></div>
  `;

  container.querySelector("#backToDashboard").addEventListener("click", () => store.navigate("dashboard"));

  container.querySelectorAll(".sort-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentSort = btn.dataset.sort;
      renderDivisionDetail(container, store);
    });
  });

  const grid = container.querySelector("#deptGrid");
  const sorted = [...divisionDetail.departments].sort(SORTS[currentSort]);
  sorted.forEach((d) => grid.appendChild(deptRow(d, store, hasAmountData)));
}
