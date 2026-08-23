import { icons } from "../icons.js";
import { escapeHtml } from "../escape.js";
import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";

// Dashboard redesign (user request, with a reference mockup): the page must
// answer, the instant it opens, "how much value came in -> which Division
// -> how many items -> how many documents" for a document-date RANGE (not
// upload date), with an optional Division filter. Every number here is
// either read straight from store.state.products/documents (already loaded
// by refreshAll()) or from store.state.dashboardOverview, which is built in
// state.js from each in-range document's authoritative, Decimal-safe
// GET /api/analytics/documents/{id}/divisions summary - this view never
// invents a qty*price formula of its own.

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

function fmtDateTime(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("th-TH", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function kpiIconCard(value, label, icon, tone) {
  return `
    <div class="kpi-icon-card">
      <div class="kpi-icon-badge tone-${tone}">${icon}</div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-label">${label}</div>
    </div>`;
}

// Naive independent Math.round() on each Division's share can sum to 99%
// or 101% - the summary table must foot to exactly 100% (user requirement).
// Largest-remainder rounding: floor every share, then hand the leftover
// percentage points to the entries with the largest fractional remainder.
function allocatePercentages(values) {
  const total = values.reduce((a, b) => a + b, 0);
  if (total <= 0) return values.map(() => 0);
  const raw = values.map((v) => (v / total) * 100);
  const floors = raw.map(Math.floor);
  const remainder = 100 - floors.reduce((a, b) => a + b, 0);
  const byRemainder = raw.map((v, i) => [v - Math.floor(v), i]).sort((a, b) => b[0] - a[0]);
  const result = [...floors];
  for (let k = 0; k < remainder; k++) result[byRemainder[k][1]] += 1;
  return result;
}

function inRange(documentDate, dateFrom, dateTo) {
  if (!documentDate) return !dateFrom && !dateTo;
  if (dateFrom && documentDate < dateFrom) return false;
  if (dateTo && documentDate > dateTo) return false;
  return true;
}

// Slim status strip - just enough to notice something needs attention and
// jump to where it's actually actionable (Documents/Review), so a
// processing/errored document never leaves the Dashboard looking blank.
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

const DIVISION_DONUT_COLORS = ["--division-1", "--division-2", "--division-3", "--division-4", "--division-5", "--division-6", "--text-faint"];

// The main graph (user-supplied reference mockup): a donut chart of each
// Division's share of today's-range value, plus a full summary table
// (Division / มูลค่า / สัดส่วน / จำนวนรายการ / จำนวนเอกสาร) with a total
// row, each row clickable to Products filtered to that Division's
// departments. When no document in range carries amount data, falls back
// to a quantity-based ("จำนวนรายการ") breakdown instead of hiding the
// chart or inventing a value.
function renderDivisionValueChart(host, overview, departmentsByDivision, onRowClick) {
  if (!overview) {
    host.innerHTML = `<div class="workspace-sub" style="padding:20px 0;text-align:center;">กำลังโหลดข้อมูลสรุป...</div>`;
    return;
  }
  // When a single Division is selected in the header filter, narrow the
  // chart/table to just that Division too - otherwise the KPI cards above
  // (scoped to the filter) and this table (always every Division) would
  // silently disagree the moment a filter is applied.
  const entries = overview.divisions.filter(
    (d) => d.rowCount > 0 && (overview.selectedDivision === "all" || d.divisionCode === overview.selectedDivision)
  );
  if (!entries.length) {
    host.innerHTML = `<div class="workspace-sub" style="padding:20px 0;text-align:center;">ไม่มีข้อมูลสินค้าในช่วงวันที่ / ฝ่ายที่เลือก</div>`;
    return;
  }
  const byValue = overview.amountAvailable;
  const metric = (d) => (byValue ? d.amount : d.rowCount);
  const sorted = [...entries].sort((a, b) => metric(b) - metric(a));
  const percentages = allocatePercentages(sorted.map(metric));
  const grandTotal = sorted.reduce((sum, d) => sum + metric(d), 0);
  const grandRowCount = sorted.reduce((sum, d) => sum + d.rowCount, 0);
  // Document count is NOT summed across the visible Division rows - one
  // document can contribute rows to several Divisions, so summing would
  // double-count it and overstate "how many documents". overview.totals
  // .documentCount is the true distinct count already used by the
  // "จำนวนเอกสาร" KPI card above, so the total row here always agrees with
  // it exactly (and correctly narrows when a single Division is selected -
  // see the entries filter above).
  const grandDocCount = overview.totals.documentCount;

  let offset = 0;
  const segments = sorted
    .map((d, i) => {
      const pct = percentages[i];
      const seg = `var(${DIVISION_DONUT_COLORS[i % DIVISION_DONUT_COLORS.length]}) ${offset}% ${offset + pct}%`;
      offset += pct;
      return seg;
    })
    .join(", ");

  const centerValue = byValue ? fmtBaht(grandTotal) : fmtNum(grandTotal);
  const centerLabel = byValue ? "มูลค่ารวม (฿)" : "จำนวนรายการรวม";

  host.innerHTML = `
    <div class="dash-division-chart-grid">
      <div class="donut-wrap">
        <div style="width:150px;height:150px;border-radius:50%;background:conic-gradient(${segments});display:flex;align-items:center;justify-content:center;">
          <div style="width:96px;height:96px;border-radius:50%;background:var(--surface);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;">
            <div class="mono" style="font-size:14px;font-weight:700;">${centerValue}</div>
            <div style="font-size:9.5px;color:var(--text-faint);">${centerLabel}</div>
          </div>
        </div>
      </div>
      <div class="data-table-wrap">
        <table class="data-table">
          <thead><tr>
            <th>Division</th>
            <th class="num">${byValue ? "มูลค่า (บาท)" : "จำนวนรายการ"}</th>
            <th class="num">สัดส่วน</th>
            <th class="num">จำนวนรายการ</th>
            <th class="num">จำนวนเอกสาร</th>
          </tr></thead>
          <tbody>
            ${sorted
              .map(
                (d, i) => `
              <tr class="division-summary-row" data-code="${escapeHtml(d.divisionCode)}" data-name="${escapeHtml(d.divisionName)}" style="cursor:pointer;">
                <td><span class="donut-legend-dot" style="background:var(${DIVISION_DONUT_COLORS[i % DIVISION_DONUT_COLORS.length]});display:inline-block;margin-right:7px;"></span>${escapeHtml(d.divisionName)}</td>
                <td class="num mono">${byValue ? fmtBaht(d.amount) + " ฿" : fmtNum(d.rowCount)}</td>
                <td class="num mono">${percentages[i]}%</td>
                <td class="num mono">${fmtNum(d.rowCount)}</td>
                <td class="num mono">${fmtNum(d.documentCount)}</td>
              </tr>`
              )
              .join("")}
          </tbody>
          <tfoot>
            <tr class="division-summary-total">
              <td>รวม</td>
              <td class="num mono">${byValue ? fmtBaht(grandTotal) + " ฿" : fmtNum(grandTotal)}</td>
              <td class="num mono">100%</td>
              <td class="num mono">${fmtNum(grandRowCount)}</td>
              <td class="num mono">${fmtNum(grandDocCount)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>`;

  host.querySelectorAll(".division-summary-row").forEach((row) => {
    row.addEventListener("click", () => {
      const depts = departmentsByDivision.get(row.dataset.code) || [];
      onRowClick(depts, row.dataset.name);
    });
  });
}

const PIE_COLORS = ["--division-1", "--division-2", "--division-3", "--division-4", "--division-5", "--division-6", "--text-faint"];
const PIE_TOP_N = 6;

// Secondary chart (kept from an earlier request): which Department has the
// most product by quantity, within the current date range/Division filter.
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
// reset to page 1 whenever the active filter (date range or Division)
// actually changes.
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];
let lastRenderedFilterKey = null;

// COLUMNS is built once at module load, but the dept column's render()
// needs the department->division map from store.state - kept as a
// module-level ref (same pattern as page/pageSize) rather than rebuilding
// COLUMNS on every render.
let departmentDivisionsRef = {};

export function renderDashboard(container, store) {
  const {
    documents, products, panel, departmentDivisions,
    dashboardDateFrom, dashboardDateTo, dashboardDivisionFilter,
    dashboardOverview, dashboardLastRefreshedAt, dashboardRefreshing,
  } = store.state;
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

  const filterKey = `${dashboardDateFrom}|${dashboardDateTo}|${dashboardDivisionFilter}`;
  if (filterKey !== lastRenderedFilterKey) {
    page = 1;
    lastRenderedFilterKey = filterKey;
  }

  // departmentsByDivision: reverse of departmentDivisionsRef, for the
  // Division select options and for turning a clicked Division row into a
  // Products deptFilter (an array of that Division's department names).
  const departmentsByDivision = new Map();
  const allDivisionOptions = new Map();
  for (const [dept, info] of Object.entries(departmentDivisionsRef)) {
    if (!info) continue;
    if (!departmentsByDivision.has(info.code)) departmentsByDivision.set(info.code, []);
    departmentsByDivision.get(info.code).push(dept);
    allDivisionOptions.set(info.code, info.name);
  }

  const docById = new Map(documents.map((d) => [d.id, d]));
  const inFilterRange = (p) => {
    const doc = docById.get(p.docId);
    if (!doc || doc.status !== "complete" || p.suspectedNonProduct) return false;
    if (!inRange(doc.documentDate, dashboardDateFrom, dashboardDateTo)) return false;
    if (dashboardDivisionFilter !== "all" && departmentDivisionsRef[p.department]?.code !== dashboardDivisionFilter) return false;
    return true;
  };
  const filteredRows = products.filter(inFilterRange);

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Dashboard</div>
      <div class="workspace-sub">สรุปภาพรวมข้อมูลตามวันที่ในเอกสาร</div>
    </div>

    <div id="dashStatusStrip"></div>

    <div class="dash-filters">
      <div class="dash-filter">
        <label for="dashDateFrom">จาก</label>
        <input type="date" id="dashDateFrom" value="${escapeHtml(dashboardDateFrom)}" />
      </div>
      <div class="dash-filter">
        <label for="dashDateTo">ถึง</label>
        <input type="date" id="dashDateTo" value="${escapeHtml(dashboardDateTo)}" />
      </div>
      <div class="dash-filter">
        <label for="dashDivisionSelect">Division</label>
        <select id="dashDivisionSelect">
          <option value="all"${dashboardDivisionFilter === "all" ? " selected" : ""}>ทั้งหมด</option>
          ${[...allDivisionOptions.entries()]
            .sort((a, b) => a[0].localeCompare(b[0]))
            .map(([code, name]) => `<option value="${escapeHtml(code)}"${dashboardDivisionFilter === code ? " selected" : ""}>${escapeHtml(name)}</option>`)
            .join("")}
        </select>
      </div>
      <div class="dash-filter-meta">
        <span>อัปเดตล่าสุด: ${fmtDateTime(dashboardLastRefreshedAt)}</span>
        <button type="button" class="icon-btn-sm" id="dashRefreshBtn" aria-label="รีเฟรช" ${dashboardRefreshing ? "disabled" : ""}>
          <span class="${dashboardRefreshing ? "spin" : ""}">${icons.refresh}</span>
        </button>
      </div>
    </div>

    <div class="kpi-icon-row">
      ${kpiIconCard(
        dashboardOverview ? (dashboardOverview.amountAvailable ? fmtBaht(dashboardOverview.totals.amount) + " ฿" : "ไม่มีข้อมูลมูลค่า") : "…",
        "มูลค่ารวม", icons.trendingUp, "success"
      )}
      ${kpiIconCard(dashboardOverview ? fmtNum(dashboardOverview.totals.rowCount) : "…", "จำนวนรายการสินค้า", icons.box, "accent")}
      ${kpiIconCard(dashboardOverview ? fmtNum(dashboardOverview.totals.documentCount) : "…", "จำนวนเอกสาร", icons.building, "purple")}
    </div>

    <div class="section-title">${dashboardOverview?.amountAvailable === false ? "สัดส่วนจำนวนรายการตาม Division" : "สัดส่วนมูลค่าตาม Division"}</div>
    <div id="dashDivisionChart"></div>

    <div class="section-title">แผนกที่มีสินค้าเข้าเยอะสุด (ตามจำนวน)</div>
    <div class="dash-panel" id="dashDeptPiePanel">
      <div id="dashDeptPie"></div>
    </div>

    <div class="section-title">รายการสินค้า</div>
    <div id="dashProductsTable"></div>
    <div id="dashProductsPagination"></div>
  `;

  container.querySelector("#dashStatusStrip").innerHTML = statusStrip(documents);
  container.querySelector('[data-strip-nav="documents"]')?.addEventListener("click", () => store.navigate("documents"));
  container.querySelector('[data-strip-nav="review"]')?.addEventListener("click", () => store.navigate("review"));

  const refetch = async (patch) => {
    try {
      await store.setDashboardOverviewFilters(patch);
    } catch (error) {
      store.set({
        errorDialog: {
          title: "โหลดข้อมูลสรุปไม่สำเร็จ",
          message: String(error?.message || error),
          onRetry: () => refetch(patch),
        },
      });
      document.dispatchEvent(new CustomEvent("show-error"));
    }
  };
  container.querySelector("#dashDateFrom").addEventListener("change", (e) => refetch({ dateFrom: e.target.value || "" }));
  container.querySelector("#dashDateTo").addEventListener("change", (e) => refetch({ dateTo: e.target.value || "" }));
  container.querySelector("#dashDivisionSelect").addEventListener("change", (e) => refetch({ division: e.target.value }));
  container.querySelector("#dashRefreshBtn").addEventListener("click", () => store.refreshAll());

  renderDivisionValueChart(container.querySelector("#dashDivisionChart"), dashboardOverview, departmentsByDivision, (depts, name) => {
    store.navigate("products", { deptFilter: depts, deptFilterLabel: name });
  });

  renderDepartmentPie(container.querySelector("#dashDeptPie"), filteredRows);

  const tableHost = container.querySelector("#dashProductsTable");
  const paginationHost = container.querySelector("#dashProductsPagination");
  const sortedRows = [...filteredRows].sort((a, b) => {
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
      emptyMessage: "ไม่มีสินค้าในช่วงวันที่ / ฝ่ายที่เลือก",
    });
    renderPaginationBar(paginationHost, {
      page, pageSize, total,
      onPageChange: (p) => { page = p; drawTable(); },
      onPageSizeChange: (size) => { pageSize = size; page = 1; drawTable(); },
    });
  }
  drawTable();
}
