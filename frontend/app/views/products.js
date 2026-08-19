import { renderProductTable } from "../components/productTable.js";

let debounceTimer = null;

export function renderProducts(container, store) {
  const { products, deptFilter, panel, searchQuery } = store.state;

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

  function currentRows(localQuery) {
    // Suspected non-product rows (POP/marketing-material internal codes,
    // explicit "free gift" items) are excluded here to keep the product
    // list and SKU counts clean - they're not deleted, just regrouped;
    // see the "ของแถม / ไม่ใช่สินค้า" view.
    let rows = products.filter((p) => !p.suspectedNonProduct);
    if (deptFilter) rows = rows.filter((p) => p.department === deptFilter);
    const q = (localQuery || "").trim().toLowerCase();
    if (q) rows = rows.filter((p) => p._search.includes(q));
    return rows;
  }

  const host = container.querySelector("#tableHost");
  const countEl = container.querySelector("#productCount");
  const visibleEl = container.querySelector("#visibleCount");

  function draw(localQuery) {
    const rows = currentRows(localQuery);
    countEl.textContent = `${rows.length.toLocaleString()} รายการ`;
    visibleEl.textContent = `${rows.length.toLocaleString()} แสดงอยู่`;
    renderProductTable(host, rows, {
      selectedRowId: panel?.rowId,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
    });
  }

  draw(searchQuery || "");

  container.querySelector("#productFilter").addEventListener("input", (e) => {
    clearTimeout(debounceTimer);
    const val = e.target.value;
    debounceTimer = setTimeout(() => draw(val), 200); // debounced, not per-keystroke
  });
}
