import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";
import { icons } from "../icons.js";
import { escapeHtml } from "../escape.js";

// Conservative classification (see pdf_document_intelligence/catalog/classify.py):
// only flags on signals specific enough that a false positive on a real
// product is implausible - internal marketing/POP barcode prefixes
// (PAQ1_/PAQ2_), or the literal phrase "ของแถม" in the product name. This
// view splits those two signal families into the reference design's two
// tabs; it never invents a third bucket or loosens the backend's matching.
function isFreebie(product) {
  return (product.nonProductReasons || []).some((r) => String(r).includes("ของแถม"));
}

const TABS = [
  { key: "freebie", label: "ของแถม", test: isFreebie },
  { key: "nonproduct", label: "ไม่ใช่สินค้า", test: (p) => !isFreebie(p) },
];

let activeTab = "freebie";
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];
let sortKey = null;
let sortDir = 1;

function fmt(v) {
  if (v === null || v === undefined || v === "") return "—";
  return escapeHtml(v);
}

function sortIcon(key) {
  return `<span class="sort-th" data-sort="${key}">${icons.chevronUpDown}</span>`;
}

function buildColumns() {
  return [
    { key: "type", label: "TYPE", render: (r) => (isFreebie(r) ? "ของแถม" : "ไม่ใช่สินค้า") },
    { key: "article", label: `ARTICLE ${sortIcon("article")}`, render: (r) => `<span class="mono">${fmt(r.fields?.article?.value)}</span>` },
    { key: "barcode", label: `BARCODE ${sortIcon("barcode")}`, render: (r) => `<span class="mono">${fmt(r.fields?.barcode?.value)}</span>` },
    { key: "name", label: `ชื่อสินค้า ${sortIcon("name")}`, render: (r) => fmt(r.fields?.name?.value) },
    { key: "dept", label: "แผนก", render: (r) => fmt(r.department) },
    { key: "qty", label: "จำนวน", align: "num", render: (r) => `<span class="mono">${fmt(r.fields?.sku_qty?.value)}</span>` },
    { key: "amount", label: "มูลค่า (฿)", align: "num", render: (r) => `<span class="mono">${fmt(r.fields?.amount?.value)}</span>` },
    { key: "status", label: "สถานะ", render: () => `<span class="pill pill-success">Active</span>` },
    {
      key: "actions",
      label: "จัดการ",
      render: () => `
        <div class="data-table-actions">
          <button type="button" class="icon-btn-sm tone-accent" data-row-action="view" aria-label="ดูรายละเอียด">${icons.eye}</button>
          <button type="button" class="icon-btn-sm" data-row-action="more" aria-label="ตัวเลือกเพิ่มเติม">${icons.moreVertical}</button>
        </div>`,
    },
  ];
}

function sortRows(rows) {
  if (!sortKey) return rows;
  const getVal = { article: (r) => r.fields?.article?.value, barcode: (r) => r.fields?.barcode?.value, name: (r) => r.fields?.name?.value }[sortKey];
  if (!getVal) return rows;
  return [...rows].sort((a, b) => String(getVal(a) ?? "").localeCompare(String(getVal(b) ?? "")) * sortDir);
}

export function renderNonProduct(container, store) {
  const { products, panel } = store.state;
  const items = products.filter((p) => p.suspectedNonProduct);
  const counts = { freebie: items.filter(isFreebie).length, nonproduct: items.filter((p) => !isFreebie(p)).length };

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">ของแถม / ไม่ใช่สินค้า</div>
      <div class="workspace-sub">รายการของแถม หรือเอกสารที่ไม่ใช่สินค้า</div>
    </div>
    ${items.length === 0
      ? `<div class="empty-state"><div class="icon">🎁</div><div class="title">ไม่พบรายการของแถม/ไม่ใช่สินค้า</div></div>`
      : `
        <div class="tab-bar" id="npTabs">
          ${TABS.map(
            (tab) => `<button type="button" class="tab-item${activeTab === tab.key ? " active" : ""}" data-tab="${tab.key}">
              ${tab.label} <span class="tab-count">${counts[tab.key]}</span>
            </button>`
          ).join("")}
        </div>
        <div id="tableHost"></div>
        <div id="paginationHost"></div>`}
  `;

  if (!items.length) return;

  container.querySelector("#npTabs").querySelectorAll(".tab-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      page = 1;
      renderNonProduct(container, store);
    });
  });

  const host = container.querySelector("#tableHost");
  const paginationHost = container.querySelector("#paginationHost");

  function draw() {
    const tab = TABS.find((t) => t.key === activeTab) || TABS[0];
    const rows = sortRows(items.filter(tab.test));
    const { pageRows, total } = paginate(rows, page, pageSize);
    renderDataTable(host, pageRows, {
      columns: buildColumns(),
      getRowId: (row) => row.rowId,
      selectedRowId: panel?.rowId,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
      emptyMessage: "ไม่มีรายการในกลุ่มนี้",
    });
    host.querySelectorAll(".sort-th").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const key = el.dataset.sort;
        sortDir = sortKey === key ? -sortDir : 1;
        sortKey = key;
        draw();
      });
    });
    renderPaginationBar(paginationHost, {
      page,
      pageSize,
      total,
      onPageChange: (p) => { page = p; draw(); },
      onPageSizeChange: (size) => { pageSize = size; page = 1; draw(); },
    });
  }

  draw();
}
