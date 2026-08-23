import { renderProductTable } from "../components/productTable.js";

const RESOLUTION_LABEL = {
  OFFICIAL_MASTER: "Official Master",
  LOCAL_MASTER: "Local Master",
  OCR: "OCR/PDF",
  MANUAL_REVIEW: "Review",
  CORRECTED: "แก้ไขแล้ว",
};

let debounceTimer = null;
let cachedProductsRef = null;
let cachedDeptFilter = null;
let cachedBaseRows = [];
let cachedQuery = null;
let cachedQueryRows = [];

// Extra in-view filters (department is already driven by store.state.deptFilter
// via navigation from other views; these add resolution-status and
// review-required narrowing directly on this view, entirely client-side over
// the already-loaded product list - no new backend call).
let resolutionFilter = "all";
let reviewFilter = "all";

function baseRows(products, deptFilter) {
  if (products === cachedProductsRef && deptFilter === cachedDeptFilter) return cachedBaseRows;
  cachedProductsRef = products;
  cachedDeptFilter = deptFilter;
  cachedBaseRows = products.filter((p) => !p.suspectedNonProduct && (!deptFilter || p.department === deptFilter));
  cachedQuery = null;
  cachedQueryRows = [];
  return cachedBaseRows;
}

function searchedRows(products, deptFilter, localQuery) {
  const rows = baseRows(products, deptFilter);
  const q = (localQuery || "").trim().toLowerCase();
  if (!q) return rows;
  if (q === cachedQuery) return cachedQueryRows;
  cachedQuery = q;
  cachedQueryRows = rows.filter((p) => p._search.includes(q));
  return cachedQueryRows;
}

function applyExtraFilters(rows) {
  return rows.filter((p) => {
    if (resolutionFilter !== "all" && p.resolutionStatus !== resolutionFilter) return false;
    if (reviewFilter === "review" && !p.reviewRequired) return false;
    if (reviewFilter === "clean" && p.reviewRequired) return false;
    return true;
  });
}

export function renderProducts(container, store) {
  const { products, deptFilter, panel, searchQuery } = store.state;
  const scrollTop = container.querySelector(".vtable-body")?.scrollTop || 0;

  const departments = [...new Set(products.map((p) => p.department).filter(Boolean))].sort();
  const resolutionOptions = Object.keys(RESOLUTION_LABEL)
    .filter((key) => products.some((p) => p.resolutionStatus === key))
    .map((key) => `<option value="${key}"${resolutionFilter === key ? " selected" : ""}>${RESOLUTION_LABEL[key]}</option>`)
    .join("");

  container.innerHTML = `
    ${deptFilter ? `<div class="back-link" id="clearDept">‹ ทุกแผนก</div>` : ""}
    <div class="workspace-header">
      <div class="workspace-title">${deptFilter || "Products"}</div>
      <div class="workspace-sub" id="productCount"></div>
    </div>
    <div class="table-toolbar">
      <input id="productFilter" type="text" placeholder="ค้นหาในตารางนี้..." value="${searchQuery || ""}" />
      <select id="productDeptSelect" class="filter-select">
        <option value=""${!deptFilter ? " selected" : ""}>ทุกแผนก</option>
        ${departments.map((d) => `<option value="${d}"${deptFilter === d ? " selected" : ""}>${d}</option>`).join("")}
      </select>
      <select id="productResolutionSelect" class="filter-select">
        <option value="all"${resolutionFilter === "all" ? " selected" : ""}>ทุกสถานะที่มา</option>
        ${resolutionOptions}
      </select>
      <select id="productReviewSelect" class="filter-select">
        <option value="all"${reviewFilter === "all" ? " selected" : ""}>ทุกสถานะตรวจสอบ</option>
        <option value="review"${reviewFilter === "review" ? " selected" : ""}>ต้องตรวจสอบเท่านั้น</option>
        <option value="clean"${reviewFilter === "clean" ? " selected" : ""}>ปกติเท่านั้น</option>
      </select>
      <span class="count-label" id="visibleCount"></span>
    </div>
    <div id="tableHost"></div>
  `;

  if (deptFilter) {
    container.querySelector("#clearDept").addEventListener("click", () => store.navigate("products", { deptFilter: null }));
  }

  const host = container.querySelector("#tableHost");
  const countEl = container.querySelector("#productCount");
  const visibleEl = container.querySelector("#visibleCount");

  function draw(localQuery, preserveScrollTop) {
    const rows = applyExtraFilters(searchedRows(products, deptFilter, localQuery));
    countEl.textContent = `${rows.length.toLocaleString()} รายการ`;
    visibleEl.textContent = `${rows.length.toLocaleString()} แสดงอยู่`;
    renderProductTable(host, rows, {
      selectedRowId: panel?.rowId,
      initialScrollTop: preserveScrollTop ? scrollTop : 0,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
    });
  }

  draw(searchQuery || "", true);

  container.querySelector("#productFilter").addEventListener("input", (e) => {
    clearTimeout(debounceTimer);
    const val = e.target.value;
    debounceTimer = setTimeout(() => draw(val, false), 200);
  });
  container.querySelector("#productDeptSelect").addEventListener("change", (e) => {
    store.navigate("products", { deptFilter: e.target.value || null });
  });
  container.querySelector("#productResolutionSelect").addEventListener("change", (e) => {
    resolutionFilter = e.target.value;
    draw(searchQuery || "", false);
  });
  container.querySelector("#productReviewSelect").addEventListener("change", (e) => {
    reviewFilter = e.target.value;
    draw(searchQuery || "", false);
  });
}
