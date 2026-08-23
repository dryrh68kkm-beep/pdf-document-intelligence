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

// Rolled up Division-first (user request: "แยกใหญ่ก่อนเป็นมูลค่าตามฝ่าย" -
// separate the bigger category first, by Division), same as the product
// table's "ฝ่าย / แผนก" column. Rendered as a donut (share of today's value)
// plus a summary table (user-supplied reference mockup: Division / มูลค่า /
// สัดส่วน / จำนวนรายการ / จำนวนเอกสาร), each row navigating to Products
// filtered to that Division's departments.
const DIVISION_DONUT_COLORS = ["--division-1", "--division-2", "--division-3", "--division-4", "--division-5", "--division-6", "--text-faint"];
const DIVISION_TOP_N = 6;

function rollupByDivision(rows) {
  const deptTotals = new Map();
  for (const row of rows) {
    const dept = row.department || "ไม่ระบุแผนก";
    const amount = row.fields.amount?.value;
    const entry = deptTotals.get(dept) || { amount: 0, count: 0, docIds: new Set() };
    entry.amount += amount ?? 0;
    entry.count += 1;
    entry.docIds.add(row.docId);
    deptTotals.set(dept, entry);
  }

  const divisions = new Map();
  for (const [dept, info] of deptTotals) {
    const divisionName = departmentDivisionsRef[dept]?.name || "ไม่ระบุฝ่าย";
    const group = divisions.get(divisionName) || { total: 0, count: 0, docIds: new Set(), depts: [] };
    group.total += info.amount;
    group.count += info.count;
    info.docIds.forEach((id) => group.docIds.add(id));
    group.depts.push(dept);
    divisions.set(divisionName, group);
  }

  return [...divisions.entries()]
    .map(([name, group]) => ({ name, total: group.total, count: group.count, docCount: group.docIds.size, depts: group.depts }))
    .sort((a, b) => b.total - a.total);
}

function renderDivisionValueChart(host, rows, amountAvailable) {
  if (!rows.length) {
    host.innerHTML = `<div class="workspace-sub" style="padding:6px 0;">ไม่มีสินค้าเข้าสำหรับวันที่นี้</div>`;
    return;
  }
  const divisionEntries = rollupByDivision(rows);
  const grandTotal = divisionEntries.reduce((sum, d) => sum + d.total, 0) || 1;

  let donutHtml = "";
  if (amountAvailable) {
    let chartEntries = divisionEntries;
    if (chartEntries.length > DIVISION_TOP_N) {
      const head = chartEntries.slice(0, DIVISION_TOP_N);
      const otherTotal = chartEntries.slice(DIVISION_TOP_N).reduce((sum, d) => sum + d.total, 0);
      chartEntries = [...head, { name: "อื่นๆ", total: otherTotal }];
    }
    let offset = 0;
    const segments = chartEntries
      .map((d, i) => {
        const pct = (d.total / grandTotal) * 100;
        const seg = `var(${DIVISION_DONUT_COLORS[i % DIVISION_DONUT_COLORS.length]}) ${offset}% ${offset + pct}%`;
        offset += pct;
        return seg;
      })
      .join(", ");
    donutHtml = `
      <div class="donut-wrap">
        <div style="width:130px;height:130px;border-radius:50%;background:conic-gradient(${segments});display:flex;align-items:center;justify-content:center;">
          <div style="width:84px;height:84px;border-radius:50%;background:var(--surface);display:flex;flex-direction:column;align-items:center;justify-content:center;">
            <div class="mono" style="font-size:14px;font-weight:700;">${fmtBaht(grandTotal)}</div>
            <div style="font-size:10px;color:var(--text-faint);">มูลค่ารวม</div>
          </div>
        </div>
        <div class="donut-legend">
          ${chartEntries
            .map(
              (d, i) => `
            <div class="donut-legend-row">
              <span class="donut-legend-dot" style="background:var(${DIVISION_DONUT_COLORS[i % DIVISION_DONUT_COLORS.length]});"></span>
              <span class="donut-legend-name">${escapeHtml(d.name)}</span>
              <span class="donut-legend-count">${fmtBaht(d.total)} ฿ · ${Math.round((d.total / grandTotal) * 100)}%</span>
            </div>`
            )
            .join("")}
        </div>
      </div>`;
  } else {
    donutHtml = `<div class="workspace-sub" style="padding:6px 0;">ไม่มีข้อมูลมูลค่าสำหรับวันที่นี้</div>`;
  }

  host.innerHTML = `
    ${donutHtml}
    <div class="data-table-wrap" style="margin-top:14px;">
      <table class="data-table">
        <thead><tr>
          <th>Division</th>
          <th class="num">มูลค่า (บาท)</th>
          <th class="num">สัดส่วน</th>
          <th class="num">จำนวนรายการ</th>
          <th class="num">จำนวนเอกสาร</th>
        </tr></thead>
        <tbody>
          ${divisionEntries
            .map(
              (d) => `
            <tr class="division-summary-row" data-depts="${escapeHtml(JSON.stringify(d.depts))}" data-name="${escapeHtml(d.name)}" style="cursor:pointer;">
              <td>${escapeHtml(d.name)}</td>
              <td class="num mono">${amountAvailable ? fmtBaht(d.total) + " ฿" : "—"}</td>
              <td class="num mono">${amountAvailable ? Math.round((d.total / grandTotal) * 100) + "%" : "—"}</td>
              <td class="num mono">${fmtNum(d.count)}</td>
              <td class="num mono">${fmtNum(d.docCount)}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>`;
}

const PIE_COLORS = ["--division-1", "--division-2", "--division-3", "--division-4", "--division-5", "--division-6", "--text-faint"];
const PIE_TOP_N = 6;

// Which department has the most product coming in today, by total
// quantity (sku_qty) - a pie chart, distinct from the value-based bar
// ranking below it. Top 6 departments get their own slice; the rest are
// folded into "อื่นๆ" so the chart stays readable regardless of how many
// departments appear on a given day.
function renderDepartmentPie(host, rows) {
  if (!rows.length) {
    host.innerHTML = `<div class="workspace-sub" style="padding:20px 0;text-align:center;">ไม่มีข้อมูล</div>`;
    return;
  }
  const totals = new Map();
  for (const row of rows) {
    const dept = row.department || "ไม่ระบุแผนก";
    const qty = row.fields.sku_qty?.value;
    totals.set(dept, (totals.get(dept) || 0) + (typeof qty === "number" ? qty : 0));
  }
  let entries = [...totals.entries()].sort((a, b) => b[1] - a[1]);
  if (entries.length > PIE_TOP_N) {
    const head = entries.slice(0, PIE_TOP_N);
    const otherTotal = entries.slice(PIE_TOP_N).reduce((sum, [, qty]) => sum + qty, 0);
    entries = [...head, ["อื่นๆ", otherTotal]];
  }
  const total = entries.reduce((sum, [, qty]) => sum + qty, 0) || 1;

  let offset = 0;
  const segments = entries
    .map(([, qty], i) => {
      const pct = (qty / total) * 100;
      const seg = `var(${PIE_COLORS[i % PIE_COLORS.length]}) ${offset}% ${offset + pct}%`;
      offset += pct;
      return seg;
    })
    .join(", ");

  host.innerHTML = `
    <div class="donut-wrap">
      <div style="width:130px;height:130px;border-radius:50%;background:conic-gradient(${segments});display:flex;align-items:center;justify-content:center;">
        <div style="width:84px;height:84px;border-radius:50%;background:var(--surface);display:flex;flex-direction:column;align-items:center;justify-content:center;">
          <div class="mono" style="font-size:18px;font-weight:700;">${fmtNum(total)}</div>
          <div style="font-size:10px;color:var(--text-faint);">หน่วยรวม</div>
        </div>
      </div>
      <div class="donut-legend">
        ${entries
          .map(
            ([dept, qty], i) => `
          <div class="donut-legend-row">
            <span class="donut-legend-dot" style="background:var(${PIE_COLORS[i % PIE_COLORS.length]});"></span>
            <span class="donut-legend-name">${escapeHtml(dept)}</span>
            <span class="donut-legend-count">${fmtNum(qty)} · ${Math.round((qty / total) * 100)}%</span>
          </div>`
          )
          .join("")}
      </div>
    </div>
  `;
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

    <div class="section-title">สินค้าตามแผนกวันนี้</div>
    <div class="dash-dept-grid">
      <div class="dash-panel">
        <div class="dash-panel-head"><span class="dash-panel-title">แผนกที่มีสินค้าเข้าเยอะสุด (ตามจำนวน)</span></div>
        <div id="dashDeptPie"></div>
      </div>
      <div class="dash-panel">
        <div class="dash-panel-head"><span class="dash-panel-title">สัดส่วนมูลค่าตามฝ่าย</span></div>
        <div id="dashDeptBars"></div>
      </div>
    </div>
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

  renderDepartmentPie(container.querySelector("#dashDeptPie"), todaysRows);

  const deptBarsHost = container.querySelector("#dashDeptBars");
  renderDivisionValueChart(deptBarsHost, todaysRows, amountAvailable);
  deptBarsHost.querySelectorAll(".division-summary-row").forEach((row) => {
    row.addEventListener("click", () => {
      store.navigate("products", { deptFilter: JSON.parse(row.dataset.depts), deptFilterLabel: row.dataset.name });
    });
  });
}
