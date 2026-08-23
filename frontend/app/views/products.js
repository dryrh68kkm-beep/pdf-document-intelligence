import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";
import { icons } from "../icons.js";
import { escapeHtml } from "../escape.js";

const RESOLUTION_LABEL = {
  OFFICIAL_MASTER: "Official Master",
  LOCAL_MASTER: "Local Master",
  OCR: "OCR/PDF",
  MANUAL_REVIEW: "Review",
  CORRECTED: "แก้ไขแล้ว",
};

let debounceTimer = null;

// Real bug (found during an audit): this view used to read the search box's
// value straight from store.state.searchQuery on every render. Any
// unrelated store.set() elsewhere in the app - a background document
// finishing OCR, a poll-triggered refreshAll() - fires the same
// store.subscribe(render) full re-render, which used to reset this input
// back to the (stale) store value and silently erase whatever the user was
// mid-typing. localSearchText is the box's actual current text, kept in
// sync on every keystroke; it's only overwritten from the store when the
// store's searchQuery itself changed (an explicit navigation from the
// global search box), tracked via lastSyncedStoreQuery.
let localSearchText = "";
let lastSyncedStoreQuery = null;

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

// Real pagination state (client-side, over the already-loaded product
// list — see components/pagination.js).
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];

function matchesDeptFilter(product, deptFilter) {
  if (!deptFilter) return true;
  if (Array.isArray(deptFilter)) return deptFilter.includes(product.department);
  return product.department === deptFilter;
}

function baseRows(products, deptFilter) {
  if (products === cachedProductsRef && deptFilter === cachedDeptFilter) return cachedBaseRows;
  cachedProductsRef = products;
  cachedDeptFilter = deptFilter;
  cachedBaseRows = products.filter((p) => !p.suspectedNonProduct && matchesDeptFilter(p, deptFilter));
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

function fmt(v) {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return v % 1 === 0 ? String(v) : v.toFixed(2);
  return escapeHtml(v);
}

function rowConfidence(f) {
  const value = f.barcode?.confidence ?? f.article?.confidence ?? f.name?.confidence;
  return value == null ? null : Math.round(value * 100);
}

const COLUMNS = [
  { key: "article", label: "ARTICLE", render: (r) => `<span class="mono">${fmt(r.fields.article?.value)}</span>` },
  { key: "barcode", label: "BARCODE", render: (r) => `<span class="mono">${fmt(r.fields.barcode?.value)}</span>` },
  { key: "name", label: "ชื่อสินค้า", render: (r) => fmt(r.fields.name?.value) },
  { key: "dept", label: "แผนก", render: (r) => fmt(r.department) },
  { key: "pu", label: "PU", align: "num", render: (r) => `<span class="mono">${fmt(r.fields.pu_qty?.value)}</span>` },
  { key: "sku", label: "SKU QTY", align: "num", render: (r) => `<span class="mono">${fmt(r.fields.sku_qty?.value)}</span>` },
  { key: "source", label: "แหล่งที่มา", render: (r) => RESOLUTION_LABEL[r.resolutionStatus] || r.resolutionStatus || "—" },
  {
    key: "confidence",
    label: "Confidence",
    align: "num",
    render: (r) => {
      const c = rowConfidence(r.fields);
      return `<span class="mono">${c == null ? "—" : c + "%"}</span>`;
    },
  },
  {
    key: "status",
    label: "สถานะ",
    render: (r) =>
      r.reviewRequired
        ? `<span class="pill pill-critical">ต้องตรวจสอบ</span>`
        : `<span class="pill pill-success">ปกติ</span>`,
  },
  {
    key: "actions",
    label: "จัดการ",
    render: () => `<button type="button" class="icon-btn-sm" data-row-action="menu" aria-label="ตัวเลือกเพิ่มเติม">${icons.moreVertical}</button>`,
  },
];

export function renderProducts(container, store) {
  const { products, deptFilter, deptFilterLabel, panel, searchQuery } = store.state;
  // deptFilter is either a single department string (picked from the
  // dropdown below, or a department-level click elsewhere) or an array of
  // department names (a Division-level click - e.g. the Dashboard's
  // "มูลค่าตามฝ่าย" table), which carries its own display name.
  const filterTitle = deptFilterLabel || (Array.isArray(deptFilter) ? null : deptFilter);

  if (searchQuery !== lastSyncedStoreQuery) {
    localSearchText = searchQuery || "";
    lastSyncedStoreQuery = searchQuery;
  }

  const departments = [...new Set(products.map((p) => p.department).filter(Boolean))].sort();
  const resolutionOptions = Object.keys(RESOLUTION_LABEL)
    .filter((key) => products.some((p) => p.resolutionStatus === key))
    .map((key) => `<option value="${key}"${resolutionFilter === key ? " selected" : ""}>${RESOLUTION_LABEL[key]}</option>`)
    .join("");

  // An unrelated background render (see localSearchText above) rebuilds
  // this whole container - preserve cursor position too, not just the
  // text, so a re-render mid-keystroke doesn't kick focus out of the box.
  const hadFocus = container.querySelector("#productFilter") === document.activeElement;
  const selectionStart = hadFocus ? container.querySelector("#productFilter").selectionStart : null;

  container.innerHTML = `
    ${deptFilter ? `<div class="back-link" id="clearDept">‹ ทุกแผนก</div>` : ""}
    <div class="workspace-header">
      <div class="workspace-title">${escapeHtml(filterTitle) || "Products"}</div>
      <div class="workspace-sub">รายการสินค้า</div>
    </div>
    <div class="filter-chip-bar">
      <input id="productFilter" class="search-input" type="text" placeholder="ค้นหาในตารางนี้..." value="${escapeHtml(localSearchText)}" />
      <select id="productDeptSelect" class="filter-chip">
        <option value=""${!deptFilter ? " selected" : ""}>ทุกแผนก</option>
        ${departments.map((d) => `<option value="${escapeHtml(d)}"${deptFilter === d ? " selected" : ""}>${escapeHtml(d)}</option>`).join("")}
      </select>
      <select id="productResolutionSelect" class="filter-chip">
        <option value="all"${resolutionFilter === "all" ? " selected" : ""}>ทุกสถานะที่มา</option>
        ${resolutionOptions}
      </select>
      <select id="productReviewSelect" class="filter-chip">
        <option value="all"${reviewFilter === "all" ? " selected" : ""}>ทุกสถานะ</option>
        <option value="review"${reviewFilter === "review" ? " selected" : ""}>ต้องตรวจสอบเท่านั้น</option>
        <option value="clean"${reviewFilter === "clean" ? " selected" : ""}>ปกติเท่านั้น</option>
      </select>
      <span class="filter-chip-count" id="visibleCount"></span>
    </div>
    <div id="tableHost"></div>
    <div id="paginationHost"></div>
  `;

  if (deptFilter) {
    container.querySelector("#clearDept").addEventListener("click", () => store.navigate("products", { deptFilter: null, deptFilterLabel: null }));
  }

  const host = container.querySelector("#tableHost");
  const paginationHost = container.querySelector("#paginationHost");
  const visibleEl = container.querySelector("#visibleCount");

  function draw(localQuery) {
    const rows = applyExtraFilters(searchedRows(products, deptFilter, localQuery));
    visibleEl.textContent = `${rows.length.toLocaleString()} รายการ`;
    const { pageRows, total } = paginate(rows, page, pageSize);
    renderDataTable(host, pageRows, {
      columns: COLUMNS,
      getRowId: (row) => row.rowId,
      selectedRowId: panel?.rowId,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
      emptyMessage: "ไม่พบรายการที่ตรงกับตัวกรอง",
    });
    renderPaginationBar(paginationHost, {
      page,
      pageSize,
      total,
      onPageChange: (p) => { page = p; draw(localQuery); },
      onPageSizeChange: (size) => { pageSize = size; page = 1; draw(localQuery); },
    });
  }

  draw(localSearchText);

  if (hadFocus) {
    const filterInput = container.querySelector("#productFilter");
    filterInput.focus();
    filterInput.setSelectionRange(selectionStart, selectionStart);
  }

  container.querySelector("#productFilter").addEventListener("input", (e) => {
    clearTimeout(debounceTimer);
    const val = e.target.value;
    localSearchText = val;
    debounceTimer = setTimeout(() => { page = 1; draw(val); }, 200);
  });
  container.querySelector("#productDeptSelect").addEventListener("change", (e) => {
    page = 1;
    store.navigate("products", { deptFilter: e.target.value || null, deptFilterLabel: null });
  });
  container.querySelector("#productResolutionSelect").addEventListener("change", (e) => {
    resolutionFilter = e.target.value;
    page = 1;
    draw(searchQuery || "");
  });
  container.querySelector("#productReviewSelect").addEventListener("change", (e) => {
    reviewFilter = e.target.value;
    page = 1;
    draw(searchQuery || "");
  });
}
