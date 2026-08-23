import { icons } from "../icons.js";
import { escapeHtml } from "../escape.js";
import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";

// Dashboard redesign (user request): the page's job is to answer, the
// instant it opens, "today's products -> which department -> how many ->
// how much" for one document date at a time (navigable day by day), not to
// be a general-purpose status board. Per-document quality/coverage detail
// still exists - it just lives on Documents/Review where it's actionable,
// collapsed here into one slim status strip. Everything below reads only
// store.state.products/documents, already loaded by refreshAll() - no new
// backend call.

function fmtNum(value) {
  return (value ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 0 });
}

function fmtBaht(value) {
  return (value ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtQty(value) {
  if (value == null) return "—";
  return value % 1 === 0 ? String(value) : value.toFixed(2);
}

function fmtDateLabel(dateStr) {
  if (!dateStr) return "—";
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" });
}

function shiftIsoDate(dateStr, delta) {
  const d = new Date(`${dateStr}T00:00:00`);
  d.setDate(d.getDate() + delta);
  return d.toISOString().slice(0, 10);
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function kpiIconCard(value, label, icon, tone) {
  return `
    <div class="kpi-icon-card">
      <div class="kpi-icon-badge tone-${tone}">${icon}</div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-label">${label}</div>
    </div>`;
}

// Slim status strip replacing the old per-document coverage/quality panels -
// just enough to notice something needs attention and jump to where it's
// actually actionable (Documents/Review).
function statusStrip(documents) {
  const processing = documents.filter((d) => d.status === "processing");
  if (processing.length) {
    return `<div class="dash-status-strip tone-warn">
      <span class="processing-hourglass" aria-hidden="true">⏳</span>
      กำลังประมวลผล ${fmtNum(processing.length)} ไฟล์
      <button type="button" class="dash-panel-link" data-strip-nav="documents">ดูที่ Documents →</button>
    </div>`;
  }
  const errored = documents.filter((d) => d.status === "error");
  if (errored.length) {
    return `<div class="dash-status-strip tone-critical">
      ⚠️ อ่านไฟล์ไม่สำเร็จ ${fmtNum(errored.length)} ไฟล์
      <button type="button" class="dash-panel-link" data-strip-nav="documents">ดูที่ Documents →</button>
    </div>`;
  }
  const reviewCount = documents.reduce((sum, d) => sum + (d.qualityCounts?.needReview ?? 0), 0);
  if (reviewCount > 0) {
    return `<div class="dash-status-strip tone-warn">
      ต้องตรวจสอบทั้งหมด ${fmtNum(reviewCount)} รายการ
      <button type="button" class="dash-panel-link" data-strip-nav="review">ดูที่ Review →</button>
    </div>`;
  }
  return `<div class="dash-status-strip tone-ok">✓ ทุกเอกสารพร้อมใช้งาน ไม่มีรายการต้องตรวจสอบ</div>`;
}

function departmentValueBars(rows, amountAvailable) {
  if (!rows.length) {
    return `<div class="workspace-sub" style="padding:6px 0;">ไม่มีสินค้าเข้าสำหรับวันที่นี้</div>`;
  }
  const totals = new Map();
  for (const row of rows) {
    const dept = row.department || "ไม่ระบุแผนก";
    const amount = row.fields.amount?.value;
    totals.set(dept, (totals.get(dept) || 0) + (amount ?? 0));
  }
  const entries = [...totals.entries()].sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map(([, amount]) => amount), 1);
  return entries
    .map(
      ([dept, amount]) => `
      <div class="recon-summary-row dept-bar-row" data-dept="${escapeHtml(dept)}">
        <div class="recon-summary-head">
          <span class="recon-summary-name">${escapeHtml(dept)}</span>
          <span class="recon-summary-frac">${amountAvailable ? fmtBaht(amount) + " ฿" : "—"}</span>
        </div>
        <div class="recon-track"><div class="recon-fill" style="width:${amountAvailable ? Math.max(2, Math.round((amount / max) * 100)) : 0}%;"></div></div>
      </div>`
    )
    .join("");
}

const COLUMNS = [
  { key: "name", label: "ชื่อสินค้า", render: (r) => escapeHtml(r.fields.name?.value) || "—" },
  {
    key: "identifier",
    label: "Article / Barcode",
    render: (r) => `
      <div class="mono" style="font-size:12px;">${escapeHtml(r.fields.article?.value) || "—"}</div>
      <div class="mono" style="font-size:11px;color:var(--text-faint);">${escapeHtml(r.fields.barcode?.value) || "—"}</div>`,
  },
  {
    key: "dept",
    label: "ฝ่าย / แผนก",
    render: (r) => {
      const division = departmentDivisionsRef[r.department]?.name;
      return `
        ${division ? `<div style="font-size:10.5px;color:var(--text-faint);">${escapeHtml(division)}</div>` : ""}
        <div>${escapeHtml(r.department) || "—"}</div>`;
    },
  },
  { key: "qty", label: "จำนวน", align: "num", render: (r) => `<span class="mono">${fmtQty(r.fields.sku_qty?.value)}</span>` },
  {
    key: "amount", label: "มูลค่ารวม", align: "num",
    render: (r) => `<span class="mono">${r.fields.amount?.value != null ? fmtBaht(r.fields.amount.value) : "—"}</span>`,
  },
];

// Module-level pagination state (same pattern as products.js/review.js) -
// reset to page 1 whenever the selected date actually changes.
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];
let lastRenderedDate = null;

// COLUMNS is built once at module load, but the dept column's render()
// needs the department->division map from store.state - kept as a
// module-level ref (same pattern as page/pageSize) rather than rebuilding
// COLUMNS on every render.
let departmentDivisionsRef = {};

export function renderDashboard(container, store) {
  const { documents, products, panel, dashboardSelectedDate, departmentDivisions } = store.state;
  departmentDivisionsRef = departmentDivisions || {};

  if (!documents.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="icon">📦</div>
        <div class="title">ยังไม่มีเอกสาร</div>
        <div>เพิ่ม PDF เพื่อเริ่มวิเคราะห์</div>
        <button class="btn btn-primary" style="margin-top:14px;" id="emptyAddBtn">＋ Add Files</button>
      </div>`;
    container.querySelector("#emptyAddBtn")?.addEventListener("click", () => document.getElementById("fileInput")?.click());
    return;
  }

  const selectedDate = dashboardSelectedDate || todayIso();
  if (selectedDate !== lastRenderedDate) {
    page = 1;
    lastRenderedDate = selectedDate;
  }

  const docById = new Map(documents.map((d) => [d.id, d]));
  const todaysRows = products.filter((p) => {
    const doc = docById.get(p.docId);
    return doc && doc.status === "complete" && doc.documentDate === selectedDate && !p.suspectedNonProduct;
  });

  const deptSet = new Set(todaysRows.map((p) => p.department).filter(Boolean));
  const amounts = todaysRows.map((p) => p.fields.amount?.value).filter((v) => v != null);
  const amountAvailable = amounts.length > 0;
  const totalAmount = amounts.reduce((a, b) => a + b, 0);

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Dashboard</div>
      <div class="workspace-sub">สรุปสินค้าที่เข้าประจำวัน</div>
    </div>

    <div id="dashStatusStrip"></div>

    <div class="dash-date-nav">
      <button type="button" class="icon-btn-sm" id="dashPrevDate" aria-label="วันก่อนหน้า">${icons.chevronLeft}</button>
      <div class="dash-date-current">
        <span class="nav-icon" aria-hidden="true">${icons.calendar}</span>
        <span class="dash-date-label">${fmtDateLabel(selectedDate)}</span>
      </div>
      <button type="button" class="icon-btn-sm" id="dashNextDate" aria-label="วันถัดไป">${icons.chevronRight}</button>
      <input type="date" id="dashDateJump" class="dash-date-jump" value="${escapeHtml(selectedDate)}" aria-label="เลือกวันที่" />
    </div>

    <div class="kpi-icon-row">
      ${kpiIconCard(fmtNum(todaysRows.length), "สินค้าวันนี้ (รายการ)", icons.box, "accent")}
      ${kpiIconCard(amountAvailable ? fmtBaht(totalAmount) + " ฿" : "—", "มูลค่ารวมวันนี้", icons.trendingUp, "success")}
      ${kpiIconCard(fmtNum(deptSet.size), "แผนกที่มีสินค้าเข้า", icons.building, "purple")}
    </div>

    <div class="section-title">รายการสินค้าวันนี้</div>
    <div id="dashProductsTable"></div>
    <div id="dashProductsPagination"></div>

    <div class="section-title">มูลค่าตามแผนกวันนี้</div>
    <div class="dash-panel" id="dashDeptBars"></div>
  `;

  container.querySelector("#dashStatusStrip").innerHTML = statusStrip(documents);
  container.querySelector('[data-strip-nav="documents"]')?.addEventListener("click", () => store.navigate("documents"));
  container.querySelector('[data-strip-nav="review"]')?.addEventListener("click", () => store.navigate("review"));

  container.querySelector("#dashPrevDate").addEventListener("click", () => {
    store.setDashboardSelectedDate(shiftIsoDate(selectedDate, -1));
  });
  container.querySelector("#dashNextDate").addEventListener("click", () => {
    store.setDashboardSelectedDate(shiftIsoDate(selectedDate, 1));
  });
  container.querySelector("#dashDateJump").addEventListener("change", (e) => {
    if (e.target.value) store.setDashboardSelectedDate(e.target.value);
  });

  const tableHost = container.querySelector("#dashProductsTable");
  const paginationHost = container.querySelector("#dashProductsPagination");
  const sortedRows = [...todaysRows].sort((a, b) => {
    const av = a.fields.amount?.value;
    const bv = b.fields.amount?.value;
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return bv - av;
  });

  function drawTable() {
    const { pageRows, total } = paginate(sortedRows, page, pageSize);
    renderDataTable(tableHost, pageRows, {
      columns: COLUMNS,
      getRowId: (row) => row.rowId,
      selectedRowId: panel?.rowId,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
      emptyMessage: "ไม่มีสินค้าเข้าสำหรับวันที่นี้",
    });
    renderPaginationBar(paginationHost, {
      page, pageSize, total,
      onPageChange: (p) => { page = p; drawTable(); },
      onPageSizeChange: (size) => { pageSize = size; page = 1; drawTable(); },
    });
  }
  drawTable();

  const deptBarsHost = container.querySelector("#dashDeptBars");
  deptBarsHost.innerHTML = departmentValueBars(todaysRows, amountAvailable);
  deptBarsHost.querySelectorAll(".dept-bar-row").forEach((row) => {
    row.addEventListener("click", () => store.navigate("products", { deptFilter: row.dataset.dept }));
  });
}
