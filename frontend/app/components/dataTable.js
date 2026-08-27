/* Shared paginated data table. Replaces the old virtual-scroll
   components/productTable.js: instead of windowing DOM rows over a
   scrollable spacer, callers slice their already-loaded array with
   pagination.js and hand this component just the rows for the current
   page (usually 10-100 rows) - real numbered-page pagination, per-view
   column definitions. */

export function renderDataTable(host, pageRows, opts) {
  const { columns, getRowId, onRowClick, onRowAction, selectedRowId, emptyMessage = "ไม่มีรายการ" } = opts;

  const wrap = document.createElement("div");
  wrap.className = "data-table-wrap";
  const table = document.createElement("table");
  table.className = "data-table";
  table.innerHTML = `
    <thead><tr>${columns.map((c) => `<th${c.align === "num" ? ' class="num"' : ""}>${c.label}</th>`).join("")}</tr></thead>
    <tbody></tbody>
  `;
  wrap.appendChild(table);
  host.innerHTML = "";
  host.appendChild(wrap);

  const tbody = table.querySelector("tbody");
  if (!pageRows.length) {
    tbody.innerHTML = `<tr><td colspan="${columns.length}" class="data-table-empty">${emptyMessage}</td></tr>`;
    return;
  }

  pageRows.forEach((row) => {
    const rowId = getRowId(row);
    const tr = document.createElement("tr");
    if (rowId === selectedRowId) tr.classList.add("selected");
    tr.innerHTML = columns
      .map((c) => `<td${c.align === "num" ? ' class="num"' : ""}>${c.render(row)}</td>`)
      .join("");
    if (onRowClick) {
      tr.style.cursor = "pointer";
      tr.tabIndex = 0;
      tr.addEventListener("click", (e) => {
        // Let interactive controls inside a cell (buttons, links) handle
        // their own click without also triggering the row-click action.
        if (e.target.closest("[data-row-action]")) return;
        onRowClick(row);
      });
      tr.addEventListener("keydown", (e) => { if (e.key === "Enter") onRowClick(row); });
    }
    // A [data-row-action] element was previously exempted from onRowClick
    // (above) but never actually wired to anything - a dead button in
    // every caller that used one (real gap found during a Products UX
    // audit: products.js's "จัดการ" column rendered a menu icon that did
    // nothing when clicked). onRowAction is optional so a caller with no
    // per-row action (and no data-row-action markup) is unaffected.
    if (onRowAction) {
      const actionEl = tr.querySelector("[data-row-action]");
      actionEl?.addEventListener("click", (e) => {
        e.stopPropagation();
        onRowAction(row, actionEl.dataset.rowAction, e);
      });
    }
    tbody.appendChild(tr);
  });
}
