import { renderProductTable } from "../components/productTable.js";

let debounceTimer = null;

export function renderProducts(container, store) {
  const { products, deptFilter, panel, searchQuery } = store.state;
  // Captured before the container is wiped below, so a re-render
  // triggered by something unrelated (e.g. a background poll tick) can
  // restore where the user was instead of snapping back to row 1.
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

  function draw(localQuery, preserveScrollTop) {
    const rows = currentRows(localQuery);
    countEl.textContent = `${rows.length.toLocaleString()} รายการ`;
    visibleEl.textContent = `${rows.length.toLocaleString()} แสดงอยู่`;
    renderProductTable(host, rows, {
      selectedRowId: panel?.rowId,
      initialScrollTop: preserveScrollTop ? scrollTop : 0,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
    });
  }

  // Preserve scroll on the initial draw (this render may have been
  // triggered by an unrelated background refresh, not the user changing
  // view/filter); a search-box edit below always resets to the top since
  // the visible row set actually changed.
  draw(searchQuery || "", true);

  container.querySelector("#productFilter").addEventListener("input", (e) => {
    clearTimeout(debounceTimer);
    const val = e.target.value;
    debounceTimer = setTimeout(() => draw(val, false), 200); // debounced, not per-keystroke
  });
}
