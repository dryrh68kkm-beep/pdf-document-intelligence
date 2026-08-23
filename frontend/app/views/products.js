import { renderProductTable } from "../components/productTable.js";

let debounceTimer = null;
let cachedProductsRef = null;
let cachedDeptFilter = null;
let cachedBaseRows = [];
let cachedQuery = null;
let cachedQueryRows = [];

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

export function renderProducts(container, store) {
  const { products, deptFilter, panel, searchQuery } = store.state;
  const scrollTop = container.querySelector(".vtable-body")?.scrollTop || 0;

  container.innerHTML = `
    ${deptFilter ? `<div class="back-link" id="clearDept">‹ ทุกแผนก</div>` : ""}
    <div class="workspace-header">
      <div class="workspace-title">${deptFilter || "Products"}</div>
      <div class="workspace-sub" id="productCount"></div>
    </div>
    <div class="table-toolbar">
      <input id="productFilter" type="text" placeholder="ค้นหาในตารางนี้..." value="${searchQuery || ""}" />
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
    const rows = searchedRows(products, deptFilter, localQuery);
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
}
