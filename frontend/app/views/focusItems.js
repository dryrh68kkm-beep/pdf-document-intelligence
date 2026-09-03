// Focus Items detail page (user request): the Dashboard card now only
// shows a compact count + total value summary, not the full item list -
// this page is where "กดเข้าไปจะขึ้นหน้าไอเท็ม" (clicking goes to the items
// page) actually lands. store.state.focusItemGroups is a snapshot handed
// over at navigation time (see dashboard.js's summary-card click handler),
// the same pattern divisionDetail.js already uses for its own drill-down -
// a direct load of this view with no snapshot (e.g. a stale back-button
// state) bounces back to the Dashboard rather than rendering empty.
import { escapeHtml } from "../escape.js";
import { icons } from "../icons.js";
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

// Cards, not a table - a card per barcode (grouped upstream in
// dashboard.js's groupFocusItemsByBarcode) summing quantity/amount across
// every row that shares it. Clicking a card's head expands it in place to
// show the individual contributing rows (document + page + qty/amount
// each) - each of those opens the real product detail side panel via
// onRowClick.
function renderFocusItemsGrid(host, pageGroups, onRowClick) {
  host.innerHTML = `
    <div class="focus-items-grid">
      ${pageGroups
        .map(
          (g, i) => `
        <div class="focus-item-card" data-group-index="${i}">
          <div class="focus-item-card-head" tabindex="0">
            <div class="focus-item-card-headtext">
              <div class="focus-item-card-name">${escapeHtml(g.name) || "—"}</div>
              <div class="focus-item-card-meta">${g.barcode ? `<span class="mono">${escapeHtml(g.barcode)}</span>` : "ไม่มี Barcode"} · ${escapeHtml(g.department) || "ไม่ระบุแผนก"}</div>
            </div>
            <span class="focus-item-card-chevron" aria-hidden="true">${icons.chevronDown}</span>
          </div>
          <div class="focus-item-card-reasons">
            ${g.reasons.map((r) => `<span class="pill pill-critical">${escapeHtml(FOCUS_REASON_LABELS[r] || r)}</span>`).join("")}
          </div>
          <div class="focus-item-card-stats">
            <span>จำนวนรวม <b class="mono">${fmtQty(g.qty)}</b></span>
            <span>มูลค่ารวม <b class="mono">${g.amountAvailable ? fmtBaht(g.amount) : "—"}</b></span>
          </div>
          ${g.rows.length > 1 ? `<div class="focus-item-card-grouped-note">รวม ${g.rows.length} รายการ (Barcode เดียวกัน)</div>` : ""}
          <div class="focus-item-card-detail" hidden>
            ${g.rows
              .map(
                ({ product }) => `
              <button type="button" class="focus-item-detail-row" data-row-id="${escapeHtml(product.rowId)}">
                <span>${escapeHtml(product.docFilename) || "—"} · หน้า ${product.page ?? "—"}</span>
                <span class="mono">${fmtQty(product.fields?.sku_qty?.value)} · ${product.fields?.amount?.value != null ? fmtBaht(product.fields.amount.value) : "—"}</span>
              </button>`
              )
              .join("")}
          </div>
        </div>`
        )
        .join("")}
    </div>
  `;

  host.querySelectorAll(".focus-item-card").forEach((card) => {
    const group = pageGroups[Number(card.dataset.groupIndex)];
    const detail = card.querySelector(".focus-item-card-detail");
    const toggle = () => {
      const willShow = detail.hidden;
      detail.hidden = !willShow;
      card.classList.toggle("expanded", willShow);
    };
    const head = card.querySelector(".focus-item-card-head");
    head.addEventListener("click", toggle);
    head.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      toggle();
    });
    detail.querySelectorAll(".focus-item-detail-row").forEach((rowBtn) => {
      rowBtn.addEventListener("click", () => {
        const match = group.rows.find((r) => r.product.rowId === rowBtn.dataset.rowId);
        if (match) onRowClick(match.product);
      });
    });
  });
}

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
      <div class="dash-panel" id="focusItemsGrid"></div>
      <div id="focusItemsPagination"></div>`
        : `<div class="empty-state"><div class="icon">✅</div><div class="title">ไม่มีรายการที่ต้องเฝ้าระวังในช่วงวันที่นี้</div></div>`
    }
  `;

  container.querySelector("#backToDashboard").addEventListener("click", () => store.navigate("dashboard"));
  container.querySelector("#focusItemsExportBtn")?.addEventListener("click", () => {
    downloadTextFile(`focus-items-${todayIso()}.csv`, focusItemsToCsv(focusItemGroups), "text/csv;charset=utf-8;");
  });

  if (!focusItemGroups.length) return;

  const gridHost = container.querySelector("#focusItemsGrid");
  const paginationHost = container.querySelector("#focusItemsPagination");

  function draw() {
    const { pageRows, total } = paginate(focusItemGroups, page, pageSize);
    renderFocusItemsGrid(gridHost, pageRows, (row) => {
      store.openPanel({ type: "product", rowId: row.rowId, data: row });
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
