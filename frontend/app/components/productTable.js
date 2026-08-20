/* Manual virtual-scroll table: renders only the rows in the visible
   window (+ buffer), regardless of how many thousands of rows are in the
   dataset - no framework/row-virtualization library dependency. */

const ROW_H = 34;
const BUFFER = 8;
const COLS = "120px 1fr 90px 60px 70px 70px 110px 50px 90px";

export function renderProductTable(container, rows, opts) {
  const { onRowClick, selectedRowId, initialScrollTop } = opts;
  container.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.className = "table-wrap";
  wrap.style.setProperty("--vt-cols", COLS);

  const head = document.createElement("div");
  head.className = "vtable-head";
  head.style.gridTemplateColumns = COLS;
  head.innerHTML = [
    "Barcode", "ชื่อสินค้า", "แผนก", "น้ำหนัก", "PU", "SKU qty", "ไฟล์", "หน้า", "สถานะ",
  ].map((h) => `<div>${h}</div>`).join("");
  wrap.appendChild(head);

  const body = document.createElement("div");
  body.className = "vtable-body";
  body.style.height = "min(60vh, 640px)";
  const spacer = document.createElement("div");
  spacer.style.height = rows.length * ROW_H + "px";
  spacer.style.position = "relative";
  body.appendChild(spacer);
  wrap.appendChild(body);
  container.appendChild(wrap);
  // The whole table is rebuilt from scratch on every re-render (state.js
  // fires a full app re-render on any store change, including ones
  // unrelated to this table's own data - e.g. a background poll tick
  // refreshing just the Documents list every few seconds). Restoring the
  // scroll position here is what keeps the row window the caller
  // actually asked for; without it every poll tick silently snapped the
  // table back to the top mid-scroll (confirmed in a real browser: 6s
  // after scrolling to 2000px, scrollTop read back as 0).
  if (initialScrollTop) body.scrollTop = initialScrollTop;

  function fmt(v) {
    if (v === null || v === undefined || v === "") return "—";
    if (typeof v === "number") return v % 1 === 0 ? String(v) : v.toFixed(2);
    return v;
  }

  function renderWindow() {
    const scrollTop = body.scrollTop;
    const viewportH = body.clientHeight;
    const startIdx = Math.max(0, Math.floor(scrollTop / ROW_H) - BUFFER);
    const endIdx = Math.min(rows.length, Math.ceil((scrollTop + viewportH) / ROW_H) + BUFFER);

    spacer.innerHTML = "";
    for (let i = startIdx; i < endIdx; i++) {
      const row = rows[i];
      const f = row.fields;
      const div = document.createElement("div");
      div.className = "vrow" + (row.rowId === selectedRowId ? " selected" : "");
      div.style.gridTemplateColumns = COLS;
      div.style.top = i * ROW_H + "px";
      div.style.height = ROW_H + "px";
      const reviewIcon = row.reviewRequired ? '<span class="flag-icon" aria-hidden="true">!</span>' : "";
      div.innerHTML = `
        <div class="mono">${fmt(f.barcode?.value)}</div>
        <div>${fmt(f.name?.value)}${reviewIcon}</div>
        <div>${fmt(row.department)}</div>
        <div class="num">${fmt(f.weight_qty?.value)}</div>
        <div class="num">${fmt(f.pu_qty?.value)}</div>
        <div class="num">${fmt(f.sku_qty?.value)}</div>
        <div title="${row.docFilename}">${row.docFilename}</div>
        <div class="num">${row.page ?? "—"}</div>
        <div><span class="band-chip band-${row.band}"><span class="dot"></span>${row.band}</span></div>
      `;
      div.tabIndex = 0;
      div.addEventListener("click", () => onRowClick(row));
      div.addEventListener("keydown", (e) => { if (e.key === "Enter") onRowClick(row); });
      spacer.appendChild(div);
    }
  }

  body.addEventListener("scroll", () => requestAnimationFrame(renderWindow));
  renderWindow();

  return { refresh: renderWindow };
}
