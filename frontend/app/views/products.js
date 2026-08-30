import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";
import { icons } from "../icons.js";
import { escapeHtml } from "../escape.js";
import { confirmMarkResolved } from "../reviewActions.js";

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
let cachedDivisionFilter = null;
let cachedBaseRows = [];
let cachedQuery = null;
let cachedQueryRows = [];

// Extra in-view filters (department is already driven by store.state.deptFilter
// via navigation from other views; these add Division, resolution-status and
// review-required narrowing directly on this view, entirely client-side over
// the already-loaded product list - no new backend call).
let divisionFilter = "all";
let resolutionFilter = "all";
let reviewFilter = "all";

function matchesDeptFilter(product, deptFilter) {
  if (!deptFilter) return true;
  if (Array.isArray(deptFilter)) return deptFilter.includes(product.department);
  return product.department === deptFilter;
}

function matchesDivisionFilter(product, divFilter, departmentDivisions) {
  if (!divFilter || divFilter === "all") return true;
  return departmentDivisions[product.department]?.code === divFilter;
}

// Real pagination state (client-side, over the already-loaded product
// list — see components/pagination.js).
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];

function baseRows(products, deptFilter, departmentDivisions) {
  if (products === cachedProductsRef && deptFilter === cachedDeptFilter && divisionFilter === cachedDivisionFilter) {
    return cachedBaseRows;
  }
  cachedProductsRef = products;
  cachedDeptFilter = deptFilter;
  cachedDivisionFilter = divisionFilter;
  cachedBaseRows = products.filter(
    (p) => !p.suspectedNonProduct && matchesDeptFilter(p, deptFilter) && matchesDivisionFilter(p, divisionFilter, departmentDivisions),
  );
  cachedQuery = null;
  cachedQueryRows = [];
  return cachedBaseRows;
}

function searchedRows(products, deptFilter, departmentDivisions, localQuery) {
  const rows = baseRows(products, deptFilter, departmentDivisions);
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
    // Real gap found during a Products UX audit: this used to always
    // render a "more options" (⋮) icon with no click handler wired
    // anywhere - a dead button that also swallowed the click instead of
    // opening the row (dataTable.js exempts [data-row-action] from
    // onRowClick so a real action handler can use it). Now a single,
    // honest action per row instead of a fake menu implying choices that
    // never existed: resolve directly from the list for a row that needs
    // review (saves opening the detail panel just to click one button),
    // or open the detail panel for one that doesn't.
    render: (r) =>
      r.reviewRequired
        ? `<button type="button" class="icon-btn-sm tone-accent" data-row-action="resolve" title="ยืนยันว่าถูกต้อง (Mark Resolved)" aria-label="ยืนยันว่าถูกต้อง">${icons.checkCircle}</button>`
        : `<button type="button" class="icon-btn-sm" data-row-action="view" title="ดูรายละเอียด" aria-label="ดูรายละเอียด">${icons.eye}</button>`,
  },
];

export function renderProducts(container, store) {
  const { deptFilter, deptFilterLabel, panel, searchQuery, departmentDivisions } = store.state;
  const products = store.getDateScopedProducts();
  // deptFilter is either a single department string (picked from the
  // dropdown below, or a department-level click elsewhere) or an array of
  // department names (a Division-level click - e.g. the Dashboard's
  // "มูลค่าตามฝ่าย" table), which carries its own display name.
  const filterTitle = deptFilterLabel || (Array.isArray(deptFilter) ? null : deptFilter);

  if (searchQuery !== lastSyncedStoreQuery) {
    localSearchText = searchQuery || "";
    lastSyncedStoreQuery = searchQuery;
  }

  // Division options come from the department->division master lookup
  // (see api.getDepartmentDivisions()), restricted to divisions that
  // actually have a department present in this date-scoped product set -
  // no empty "ฝ่าย" entries with nothing under them.
  const presentDepartments = new Set(products.map((p) => p.department).filter(Boolean));
  const divisionMap = new Map();
  presentDepartments.forEach((dept) => {
    const div = departmentDivisions[dept];
    if (div && !divisionMap.has(div.code)) divisionMap.set(div.code, div.name);
  });
  const divisions = [...divisionMap.entries()].sort((a, b) => a[0].localeCompare(b[0]));

  // The แผนก dropdown is scoped to the selected ฝ่าย, so picking a Division
  // first narrows which Departments are even offered - a department without
  // a known Division (not in departmentDivisions) is only ever shown under
  // "ทุกฝ่าย" so it never silently disappears from the list.
  const departments = [...presentDepartments]
    .filter((dept) => divisionFilter === "all" || departmentDivisions[dept]?.code === divisionFilter)
    .sort();

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
      <select id="productDivisionSelect" class="filter-chip">
        <option value="all"${divisionFilter === "all" ? " selected" : ""}>ทุกฝ่าย</option>
        ${divisions.map(([code, name]) => `<option value="${escapeHtml(code)}"${divisionFilter === code ? " selected" : ""}>${escapeHtml(name)}</option>`).join("")}
      </select>
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
    const rows = applyExtraFilters(searchedRows(products, deptFilter, departmentDivisions, localQuery));
    visibleEl.textContent = `${rows.length.toLocaleString()} รายการ`;
    const { pageRows, total } = paginate(rows, page, pageSize);
    renderDataTable(host, pageRows, {
      columns: COLUMNS,
      getRowId: (row) => row.rowId,
      selectedRowId: panel?.rowId,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
      onRowAction: (row, action) => {
        if (action === "resolve") confirmMarkResolved(store, row);
        else store.openPanel({ type: "product", rowId: row.rowId, data: row });
      },
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
  container.querySelector("#productDivisionSelect").addEventListener("change", (e) => {
    divisionFilter = e.target.value || "all";
    page = 1;
    // A department picked under the previous Division may not belong to the
    // newly selected one - clear it rather than silently keep filtering by
    // a department that's no longer even listed in the แผนก dropdown.
    const currentDept = Array.isArray(deptFilter) ? null : deptFilter;
    const stillValid =
      divisionFilter === "all" || !currentDept || departmentDivisions[currentDept]?.code === divisionFilter;
    if (stillValid) {
      // The แผนก dropdown's own option list is scoped to divisionFilter, so
      // a plain draw() (table/pagination only) would leave it showing the
      // wrong departments - the whole view needs rebuilding, not just rows.
      renderProducts(container, store);
    } else {
      store.navigate("products", { deptFilter: null, deptFilterLabel: null });
    }
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
