/* Real (numbered-page) pagination over an already-fully-loaded, in-memory
   array — replaces the previous virtual-scroll pattern everywhere a table
   is shown (Product Master, Products, Review Queue, ของแถม/ไม่ใช่สินค้า,
   Documents). All the underlying data already arrives complete from the
   backend (/api/products, /api/master/local, /api/documents), so this is
   pure client-side slicing - no backend change needed. */

import { icons } from "../icons.js";

export const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

/** Slice `rows` down to the requested page, clamping `page` into range. */
export function paginate(rows, page, pageSize) {
  const total = rows.length;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const clampedPage = Math.min(Math.max(1, page), totalPages);
  const start = (clampedPage - 1) * pageSize;
  const pageRows = rows.slice(start, start + pageSize);
  return { pageRows, total, totalPages, page: clampedPage, start };
}

/** Compact page-number list with ellipses, e.g. 1 2 3 4 5 … 42 */
function pageNumbers(page, totalPages) {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }
  const nums = new Set([1, 2, totalPages - 1, totalPages, page - 1, page, page + 1]);
  const sorted = [...nums].filter((n) => n >= 1 && n <= totalPages).sort((a, b) => a - b);
  const out = [];
  let prev = null;
  for (const n of sorted) {
    if (prev !== null && n - prev > 1) out.push("...");
    out.push(n);
    prev = n;
  }
  return out;
}

/**
 * Renders the "แสดง X ถึง Y จาก Z รายการ" + prev/numbered-pages/next +
 * optional page-size selector footer into `host`, and wires up its
 * controls. Call again (e.g. from the owning view's own render) whenever
 * page/pageSize/total change.
 */
export function renderPaginationBar(host, { page, pageSize, total, onPageChange, onPageSizeChange, showPageSize = true }) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const clampedPage = Math.min(Math.max(1, page), totalPages);
  const from = total === 0 ? 0 : (clampedPage - 1) * pageSize + 1;
  const to = Math.min(total, clampedPage * pageSize);

  const numbers = pageNumbers(clampedPage, totalPages);

  host.innerHTML = `
    <div class="pagination-bar">
      <div class="pagination-summary">แสดง ${from.toLocaleString("th-TH")} ถึง ${to.toLocaleString("th-TH")} จาก ${total.toLocaleString("th-TH")} รายการ</div>
      <div class="pagination-controls">
        <button type="button" class="pagination-btn" data-page="${clampedPage - 1}" ${clampedPage <= 1 ? "disabled" : ""} aria-label="หน้าก่อนหน้า">${icons.chevronLeft}</button>
        ${numbers
          .map((n) =>
            n === "..."
              ? `<span class="pagination-ellipsis">…</span>`
              : `<button type="button" class="pagination-btn${n === clampedPage ? " active" : ""}" data-page="${n}">${n}</button>`
          )
          .join("")}
        <button type="button" class="pagination-btn" data-page="${clampedPage + 1}" ${clampedPage >= totalPages ? "disabled" : ""} aria-label="หน้าถัดไป">${icons.chevronRight}</button>
        ${showPageSize
          ? `<select class="pagination-size-select" id="pageSizeSelect">
              ${PAGE_SIZE_OPTIONS.map((n) => `<option value="${n}"${n === pageSize ? " selected" : ""}>${n} / หน้า</option>`).join("")}
            </select>`
          : ""}
      </div>
    </div>
  `;

  host.querySelectorAll(".pagination-btn[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = Number(btn.dataset.page);
      if (target >= 1 && target <= totalPages && target !== clampedPage) onPageChange(target);
    });
  });
  host.querySelector("#pageSizeSelect")?.addEventListener("change", (e) => {
    onPageSizeChange(Number(e.target.value));
  });
}
