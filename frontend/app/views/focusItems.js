// Focus Items detail page (user request): the Dashboard card only shows a
// compact count + total value summary, not the full item list - this page
// is where "กดเข้าไปจะขึ้นหน้าไอเท็ม" (clicking goes to the items page)
// lands. store.state.focusItemGroups is a snapshot handed over at
// navigation time (see dashboard.js's summary-card click handler), the
// same pattern divisionDetail.js already uses for its own drill-down - a
// direct load of this view with no snapshot (e.g. a stale back-button
// state) bounces back to the Dashboard rather than rendering empty.
//
// Rendered as a normal data table (user request: "ทำให้เป็นรายการปกติ
// ไม่ใช่การ์ด" - a regular list, not cards), the same renderDataTable
// component every other list view (Products/Review/Documents) uses, not a
// bespoke card grid.
import { escapeHtml } from "../escape.js";
import { icons } from "../icons.js";
import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";
import { FOCUS_REASON_LABELS } from "./dashboard.js";

function fmtNum(n) {
  return (n ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

function fmtBaht(n) {
  return "฿" + (n ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtQty(n) {
  if (n == null) return "—";
  return n % 1 === 0 ? n.toLocaleString("th-TH") : n.toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

function csvField(value) {
  const s = value === null || value === undefined ? "" : String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function focusItemsToCsv(focusGroups) {
  const header = ["Barcode", "ชื่อสินค้า", "แผนก", "เหตุผล", "จำนวนรวม", "มูลค่ารวม", "จำนวนรายการที่รวม"];
  const lines = [header.map(csvField).join(",")];
  for (const g of focusGroups) {
    lines.push(
      [
        g.barcode || "",
        g.name || "",
        g.department || "",
        g.reasons.map((r) => FOCUS_REASON_LABELS[r] || r).join(" / "),
        g.qty,
        g.amountAvailable ? g.amount : "",
        g.rows.length,
      ]
        .map(csvField)
        .join(","),
    );
  }
  return lines.join("\r\n");
}

// "﻿" (UTF-8 BOM) so Excel on Windows - the primary user of this export,
// per the rest of this app's Thai-locale/DD-MM-YYYY conventions - reads
// the Thai text correctly instead of mojibake.
function downloadTextFile(filename, content, mimeType) {
  const blob = new Blob(["﻿" + content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];

// One row per barcode group (see groupFocusItemsByBarcode in dashboard.js)
// - quantity/amount already summed across every contributing row. A group
// merging several document lines shows that count in its own column
// rather than an inline expand; the row itself opens the first
// contributing row's product detail panel (same target every other
// list view's row click opens), which is enough to find and verify the
// item without needing every underlying line surfaced inline.
const COLUMNS = [
  { key: "name", label: "ชื่อสินค้า", render: (g) => escapeHtml(g.name) || "—" },
  { key: "barcode", label: "BARCODE", render: (g) => (g.barcode ? `<span class="mono">${escapeHtml(g.barcode)}</span>` : "—") },
  { key: "dept", label: "แผนก", render: (g) => escapeHtml(g.department) || "—" },
  {
    key: "reason",
    label: "เหตุผล",
    render: (g) => g.reasons.map((r) => `<span class="pill pill-critical">${escapeHtml(FOCUS_REASON_LABELS[r] || r)}</span>`).join(" "),
  },
  { key: "qty", label: "จำนวนรวม", align: "num", render: (g) => `<span class="mono">${fmtQty(g.qty)}</span>` },
  { key: "amount", label: "มูลค่ารวม", align: "num", render: (g) => `<span class="mono">${g.amountAvailable ? fmtBaht(g.amount) : "—"}</span>` },
  { key: "rows", label: "รวมจาก", align: "num", render: (g) => `${fmtNum(g.rows.length)} รายการ` },
  {
    key: "actions",
    label: "จัดการ",
    render: () => `<button type="button" class="icon-btn-sm tone-accent" data-row-action="view" title="ดูรายละเอียด" aria-label="ดูรายละเอียด">${icons.eye}</button>`,
  },
];

export function renderFocusItems(container, store) {
  const { focusItemGroups } = store.state;
  if (!focusItemGroups) {
    store.navigate("dashboard");
    return;
  }

  const amountAvailable = focusItemGroups.some((g) => g.amountAvailable);
  const totalAmount = focusItemGroups.reduce((sum, g) => sum + (g.amountAvailable ? g.amount : 0), 0);
  const totalQty = focusItemGroups.reduce((sum, g) => sum + g.qty, 0);

  container.innerHTML = `
    <div class="back-link" id="backToDashboard">‹ กลับไปหน้า Dashboard</div>
    <div class="workspace-header">
      <div class="workspace-title">สินค้าเฝ้าระวัง (Focus Items)</div>
      <div class="workspace-sub">${fmtNum(focusItemGroups.length)} รายการ</div>
    </div>
    ${
      focusItemGroups.length
        ? `
      <div class="kpi-row">
        <div class="kpi-card"><div class="kpi-value">${fmtNum(focusItemGroups.length)}</div><div class="kpi-label">สินค้า</div></div>
        <div class="kpi-card"><div class="kpi-value">${fmtNum(totalQty)}</div><div class="kpi-label">จำนวนรวม</div></div>
        ${amountAvailable ? `<div class="kpi-card"><div class="kpi-value">฿ ${fmtBaht(totalAmount)}</div><div class="kpi-label">มูลค่ารวม</div></div>` : ""}
      </div>
      <div class="focus-items-head">
        <div class="section-title" style="margin:0;">รายการทั้งหมด</div>
        <button type="button" class="btn btn-sm" id="focusItemsExportBtn">${icons.download} Export CSV</button>
      </div>
      <div id="focusItemsTable"></div>
      <div id="focusItemsPagination"></div>`
        : `<div class="empty-state"><div class="icon">✅</div><div class="title">ไม่มีรายการที่ต้องเฝ้าระวังในช่วงวันที่นี้</div></div>`
    }
  `;

  container.querySelector("#backToDashboard").addEventListener("click", () => store.navigate("dashboard"));
  container.querySelector("#focusItemsExportBtn")?.addEventListener("click", () => {
    downloadTextFile(`focus-items-${todayIso()}.csv`, focusItemsToCsv(focusItemGroups), "text/csv;charset=utf-8;");
  });

  if (!focusItemGroups.length) return;

  const tableHost = container.querySelector("#focusItemsTable");
  const paginationHost = container.querySelector("#focusItemsPagination");

  function draw() {
    const { pageRows, total } = paginate(focusItemGroups, page, pageSize);
    const openFirstRow = (g) => store.openPanel({ type: "product", rowId: g.rows[0].product.rowId, data: g.rows[0].product });
    renderDataTable(tableHost, pageRows, {
      columns: COLUMNS,
      getRowId: (g) => g.barcode || g.rows[0]?.product.rowId,
      onRowClick: openFirstRow,
      onRowAction: openFirstRow,
      emptyMessage: "ไม่มีรายการ",
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
