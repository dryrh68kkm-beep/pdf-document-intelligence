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

function pad2(n) {
  return String(n).padStart(2, "0");
}

// DD/MM/YYYY - shown next to the native <input type="date"> below (user
// request): that input's own displayed format follows the browser/OS
// locale (e.g. MM/DD/YYYY on an en-US system) and can't be forced via
// markup, so this label is the one place the date's format is actually
// guaranteed day/month/year regardless of the viewer's browser settings.
function fmtDateDMY(iso) {
  if (!iso) return "—";
  const d = new Date(`${iso}T00:00:00`);
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()}`;
}

// DD/MM/YYYY HH:mm per the reference mockup's exact format (spec section 6).
function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return `${pad2(d.getDate())}/${pad2(d.getMonth() + 1)}/${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function isoDaysAgo(n) {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function isoMonthStart() {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-01`;
}

// Focus Items (user request, Loss Prevention watch-list): a card surfacing
// only the rows an LP reviewer actually needs eyes on, out of possibly
// thousands - high-risk categories (alcohol, milk powder, large
// appliances) regardless of value, plus any row that's simply expensive or
// a big-quantity line item, since either is worth a second look on its
// own. Keyword lists and thresholds are the user's own stated criteria
// (2026-09 request) - kept as named constants, not re-derived from
// anything, so they can be tuned in one place without touching the
// matching logic itself.
const FOCUS_LIQUOR_DEPARTMENT = "LIQUOR";
const FOCUS_NAME_KEYWORDS = {
  liquor: ["เหล้า", "เบียร์", "วิสกี้", "ไวน์"],
  milkPowder: ["นมผง", "milk powder"],
  largeAppliance: ["ตู้เย็น", "ทีวี", "แอร์", "เครื่องซักผ้า"],
};
const FOCUS_AMOUNT_THRESHOLD = 1000;
const FOCUS_QTY_THRESHOLD = 100;

function _nameHasAnyKeyword(name, keywords) {
  const lower = (name || "").toLowerCase();
  return keywords.some((k) => lower.includes(k.toLowerCase()));
}

// Pure (no DOM/imports) so it's executed directly via Node in tests,
// matching this project's established pattern for Dashboard business
// logic (see buildDashboardOverview in state.js). Returns the matched
// reason codes (empty array = not a focus item) rather than a plain
// boolean, so the card can show *why* each row was flagged instead of
// just that it was.
function focusItemReasons(product) {
  const reasons = [];
  const name = product.fields?.name?.value;
  if (product.department === FOCUS_LIQUOR_DEPARTMENT || _nameHasAnyKeyword(name, FOCUS_NAME_KEYWORDS.liquor)) {
    reasons.push("liquor");
  }
  if (_nameHasAnyKeyword(name, FOCUS_NAME_KEYWORDS.milkPowder)) reasons.push("milkPowder");
  if (_nameHasAnyKeyword(name, FOCUS_NAME_KEYWORDS.largeAppliance)) reasons.push("largeAppliance");
  const amount = product.fields?.amount?.value;
  if (typeof amount === "number" && amount >= FOCUS_AMOUNT_THRESHOLD) reasons.push("highAmount");
  const qty = product.fields?.sku_qty?.value;
  if (typeof qty === "number" && qty >= FOCUS_QTY_THRESHOLD) reasons.push("bigLot");
  return reasons;
}

const FOCUS_REASON_LABELS = {
  liquor: "เครื่องดื่มแอลกอฮอล์",
  milkPowder: "นมผง",
  largeAppliance: "เครื่องใช้ไฟฟ้าขนาดใหญ่",
  highAmount: `มูลค่า ≥ ${FOCUS_AMOUNT_THRESHOLD.toLocaleString("th-TH")} บาท`,
  bigLot: `จำนวน ≥ ${FOCUS_QTY_THRESHOLD.toLocaleString("th-TH")} ชิ้น`,
};

// Date-range shortcuts (spec section 2): all computed off today's real
// calendar date, no new backend call - setDashboardOverviewFilters already
// accepts an explicit {dateFrom, dateTo} pair.
const DATE_SHORTCUTS = [
  { label: "วันนี้", range: () => [todayIso(), todayIso()] },
  { label: "เมื่อวาน", range: () => [isoDaysAgo(1), isoDaysAgo(1)] },
  { label: "7 วัน", range: () => [isoDaysAgo(6), todayIso()] },
  { label: "เดือนนี้", range: () => [isoMonthStart(), todayIso()] },
];

function kpiIconCard(value, label, icon, hexColor) {
  return `
    <div class="kpi-icon-card">
      <div class="kpi-icon-badge tone-solid" style="background:${hexColor};">${icon}</div>
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

// Fixed Division colors (user request: "สีต้องตรงกันทุกจุด... ห้ามสุ่มสีใหม่
// ทุกครั้งที่ render"). Keyed by Division NAME rather than the numeric code
// the user's reference list paired each color with - verified against the
// real master catalog (via GET /api/analytics/documents/{id}/divisions)
// that its own codes don't match the reference list's assumed pairing
// (e.g. this catalog's "01" is HARD LINE, not SOFT LINE as the reference
// implied), so keying by code would silently mis-color HARD LINE with the
// color meant for SOFT LINE. The name is what a viewer actually reads, so
// that's what stays stably paired with its color - never by render-order
// index, so a Division keeps the same color everywhere (donut, legend,
// ranked chart) regardless of sort order or which date range is selected.
// A name outside this fixed set still gets a *stable* color via a
// deterministic hash of the name, not array position.
const DIVISION_COLOR_BY_NAME = {
  "SOFT LINE": "#2563EB",
  "HOME LINE": "#18B58B",
  "DRY FOOD": "#F5A623",
  "FRESH FOOD": "#EF6670",
  "PHARMACY": "#9B59D0",
  "HARD LINE": "#38A3DB",
};
const DIVISION_FALLBACK_PALETTE = ["#3478F6", "#2DB486", "#D99A1F", "#9560D8", "#EF6570", "#4D91A8"];
function colorForDivision(name) {
  const key = (name || "?").toUpperCase().trim();
  if (DIVISION_COLOR_BY_NAME[key]) return DIVISION_COLOR_BY_NAME[key];
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) >>> 0;
  return DIVISION_FALLBACK_PALETTE[hash % DIVISION_FALLBACK_PALETTE.length];
}

// Shared prep for the Division value chart: filtered/sorted entries
// (narrowed to the selected Division, if any), percentages that foot to
// exactly 100%, and the real grand totals from the authoritative overview.
function prepareDivisionEntries(overview) {
  if (!overview) return null;
  const entries = overview.divisions.filter(
    (d) => d.rowCount > 0 && (overview.selectedDivision === "all" || d.divisionCode === overview.selectedDivision)
  );
  if (!entries.length) return { entries: [] };
  const byValue = overview.amountAvailable;
  const metric = (d) => (byValue ? d.amount : d.rowCount);
  const sorted = [...entries].sort((a, b) => metric(b) - metric(a));
  const percentages = allocatePercentages(sorted.map(metric));
  const grandTotal = sorted.reduce((sum, d) => sum + metric(d), 0);
  const grandRowCount = sorted.reduce((sum, d) => sum + d.rowCount, 0);
  return { entries: sorted, byValue, metric, percentages, grandTotal, grandRowCount };
}

// One decision-focused Division chart replaces the old donut + duplicate
// summary table. Horizontal bars make magnitude directly comparable while
// the aligned columns preserve exact value, share, and row-count reading.
// Rows retain the existing drill-down into Products without adding an
// extra visible action column. When amount data is unavailable, the same
// component clearly falls back to row count rather than inventing ฿0.
function renderDivisionValueChart(host, overview, departmentsByDivision, onRowClick) {
  const prepared = prepareDivisionEntries(overview);
  if (!prepared) {
    host.innerHTML = `<div class="workspace-sub" style="padding:20px 0;text-align:center;">กำลังโหลดข้อมูลสรุป...</div>`;
    return;
  }
  if (!prepared.entries.length) {
    host.innerHTML = `<div class="workspace-sub" style="padding:20px 0;text-align:center;">ไม่มีข้อมูลสินค้าในช่วงวันที่ / ฝ่ายที่เลือก</div>`;
    return;
  }
  const { entries, byValue, metric, percentages, grandTotal, grandRowCount } = prepared;
  const maxMetric = Math.max(...entries.map(metric), 1);
  const metricLabel = byValue ? "มูลค่า (บาท)" : "จำนวนรายการ";

  host.innerHTML = `
    <div class="division-value-table-wrap">
      <table class="division-value-table">
        <thead><tr>
          <th>Division</th>
          <th class="division-value-bar-head" aria-label="กราฟเปรียบเทียบ"></th>
          <th class="num">${metricLabel}</th>
          <th class="num">สัดส่วน</th>
          <th class="num">จำนวนรายการ</th>
        </tr></thead>
        <tbody>
          ${entries
            .map(
              (d, i) => `
            <tr class="division-value-row" tabindex="0" role="link" title="ดูสินค้าใน ${escapeHtml(d.divisionName)}" data-code="${escapeHtml(d.divisionCode)}" data-name="${escapeHtml(d.divisionName)}">
              <td><span class="division-value-name"><span class="donut-legend-dot" style="background:${colorForDivision(d.divisionName)};"></span>${escapeHtml(d.divisionName)}</span></td>
              <td class="division-value-bar-cell">
                <span class="division-value-track" aria-hidden="true">
                  <span class="division-value-fill" style="width:${Math.max(1.5, (metric(d) / maxMetric) * 100)}%;background:${colorForDivision(d.divisionName)};"></span>
                </span>
              </td>
              <td class="num mono division-value-amount">${byValue ? fmtBaht(d.amount) : fmtNum(d.rowCount)}</td>
              <td class="num mono">${percentages[i]}%</td>
              <td class="num mono">${fmtNum(d.rowCount)}</td>
            </tr>`
            )
            .join("")}
        </tbody>
        <tfoot>
          <tr class="division-value-total">
            <td colspan="2">รวม</td>
            <td class="num mono">${byValue ? fmtBaht(grandTotal) : fmtNum(grandTotal)}</td>
            <td class="num mono">100%</td>
            <td class="num mono">${fmtNum(grandRowCount)}</td>
          </tr>
        </tfoot>
      </table>
    </div>`;

  const clickRow = (code, name) => {
    const depts = departmentsByDivision.get(code) || [];
    onRowClick(depts, name);
  };
  host.querySelectorAll(".division-value-row").forEach((row) => {
    row.addEventListener("click", (e) => {
      clickRow(row.dataset.code, row.dataset.name);
    });
    row.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      clickRow(row.dataset.code, row.dataset.name);
    });
  });
}

const FOCUS_ITEMS_DISPLAY_CAP = 30;

// A card, not a full paginated table (Products already covers that): the
// point is a quick LP scan of "what's flagged today", so this shows the
// highest-value matches up to a cap and says plainly when more exist
// rather than silently truncating.
function renderFocusItemsPanel(host, focusRows, onRowClick) {
  if (!focusRows.length) {
    host.innerHTML = `<div class="workspace-sub" style="padding:20px 0;text-align:center;">ไม่มีรายการที่ต้องเฝ้าระวังในช่วงวันที่นี้</div>`;
    return;
  }

  const shown = focusRows.slice(0, FOCUS_ITEMS_DISPLAY_CAP);
  host.innerHTML = `
    <div class="doc-table-wrap">
      <table class="doc-table">
        <thead>
          <tr>
            <th>ชื่อสินค้า</th>
            <th>Barcode</th>
            <th>แผนก</th>
            <th>เหตุผล</th>
            <th class="num">จำนวน</th>
            <th class="num">มูลค่า</th>
          </tr>
        </thead>
        <tbody>
          ${shown
            .map(
              ({ product, reasons }) => `
            <tr class="doc-table-row focus-items-row" data-row-id="${escapeHtml(product.rowId)}" tabindex="0">
              <td>${escapeHtml(product.fields?.name?.value) || "—"}</td>
              <td><span class="mono">${escapeHtml(product.fields?.barcode?.value) || "—"}</span></td>
              <td>${escapeHtml(product.department) || "—"}</td>
              <td>${reasons.map((r) => `<span class="pill pill-critical">${escapeHtml(FOCUS_REASON_LABELS[r] || r)}</span>`).join(" ")}</td>
              <td class="num"><span class="mono">${fmtQty(product.fields?.sku_qty?.value)}</span></td>
              <td class="num"><span class="mono">${product.fields?.amount?.value != null ? fmtBaht(product.fields.amount.value) : "—"}</span></td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>
    ${
      focusRows.length > FOCUS_ITEMS_DISPLAY_CAP
        ? `<div class="workspace-sub" style="padding:10px 4px 0;">แสดง ${FOCUS_ITEMS_DISPLAY_CAP} จาก ${fmtNum(focusRows.length)} รายการ (เรียงตามมูลค่าสูงสุด)</div>`
        : ""
    }
  `;

  host.querySelectorAll(".focus-items-row").forEach((tr) => {
    const rowId = tr.dataset.rowId;
    const match = shown.find((f) => f.product.rowId === rowId);
    if (!match) return;
    const activate = () => onRowClick(match.product);
    tr.addEventListener("click", activate);
    tr.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      e.preventDefault();
      activate();
    });
  });
}

const PIE_COLORS = ["--division-1", "--division-2", "--division-3", "--division-4", "--division-5", "--division-6", "--text-faint"];
const PIE_TOP_N = 6;

// Secondary chart (kept from an earlier request, redrawn per user request
// as a horizontal color-coded bar chart instead of a donut): which
// Department has the most product by quantity, within the current date
// range/Division filter.
function renderDepartmentBarChart(host, rows) {
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
  const maxQty = Math.max(...entries.map(([, qty]) => qty), 1);

  host.innerHTML = `
    <div class="dept-bar-chart">
      ${entries
        .map(
          ([dept, qty], i) => `
        <div class="dept-bar-chart-row">
          <div class="dept-bar-chart-label">
            <span class="donut-legend-dot" style="background:var(${PIE_COLORS[i % PIE_COLORS.length]});"></span>
            ${escapeHtml(dept)}
          </div>
          <div class="recon-track"><div class="recon-fill" style="width:${Math.max(2, Math.round((qty / maxQty) * 100))}%;background:var(${PIE_COLORS[i % PIE_COLORS.length]});"></div></div>
          <div class="dept-bar-chart-value mono">${fmtNum(qty)} · ${Math.round((qty / total) * 100)}%</div>
        </div>`
        )
        .join("")}
    </div>
  `;
}

// Status badge (spec section 15): reuses the app's existing .pill system
// (see products.js/review.js) rather than a new one. suspectedNonProduct
// rows are already filtered out upstream, so only two real states apply to
// a Dashboard product row today: needs review, or normal - a fabricated
// "High Risk"/"Processing" distinction isn't backed by any real per-row
// field, so it's not invented here (see the final report's "not changed"
// list).
function statusBadge(row) {
  if (row.reviewRequired) return `<span class="pill pill-warning">ต้องตรวจ</span>`;
  return `<span class="pill pill-success">ปกติ</span>`;
}

const COLUMNS = [
  { key: "name", label: "ชื่อสินค้า", render: (r) => escapeHtml(r.fields.name?.value) || "—" },
  { key: "barcode", label: "Barcode", render: (r) => `<span class="mono" style="font-weight:600;">${escapeHtml(r.fields.barcode?.value) || "—"}</span>` },
  { key: "article", label: "Article", render: (r) => `<span class="mono">${escapeHtml(r.fields.article?.value) || "—"}</span>` },
  {
    key: "dept",
    label: "Division / Department",
    render: (r) => {
      const division = departmentDivisionsRef[r.department]?.name;
      return `
        ${division ? `<div style="font-size:10.5px;color:var(--text-faint);">${escapeHtml(division)}</div>` : ""}
        <div>${escapeHtml(r.department) || "—"}</div>`;
    },
  },
  { key: "qty", label: "SKU Qty", align: "num", render: (r) => `<span class="mono">${fmtQty(r.fields.sku_qty?.value)}</span>` },
  {
    key: "unitPrice", label: "ราคาต่อหน่วย", align: "num",
    // unit_price is the master catalog's own CURRENT_COST, looked up by
    // barcode server-side (pdf_document_intelligence/api/rows.py) - never
    // recomputed here. null (no catalog cost for this barcode) renders as
    // "—", never a fabricated 0.
    render: (r) => `<span class="mono">${r.fields.unit_price?.value != null ? fmtBaht(r.fields.unit_price.value) : "—"}</span>`,
  },
  {
    key: "amount", label: "มูลค่า", align: "num",
    // amount = unit_price * sku_qty, computed once in Decimal on the
    // backend (same file as above) and never recomputed on the frontend.
    render: (r) => `<span class="mono" style="font-weight:600;">${r.fields.amount?.value != null ? fmtBaht(r.fields.amount.value) : "—"}</span>`,
  },
  { key: "status", label: "สถานะ", render: statusBadge },
];

// Module-level pagination state (same pattern as products.js/review.js) -
// reset to page 1 whenever the active filter (date range or Division)
// actually changes.
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];
let lastRenderedFilterKey = null;

// Product-list search/filter/sort (spec section 13-14) - kept as local
// module state and applied by redrawing only the table/pagination (see
// drawTable() below), not a full store.set()-triggered re-render, so
// typing in the search box or changing sort stays cheap even with tens of
// thousands of rows loaded. localSearchText mirrors products.js's own
// fix for the same class of bug: an unrelated background render (a poll
// noticing a document finished, another tab's edit) must not wipe
// whatever the user is mid-typing, so the input reads from this local
// variable already, not by re-syncing from anywhere.
let localSearchText = "";
let localDeptFilter = "";
let sortKey = "amount"; // amount | qty | name | dept

const SORT_COMPARATORS = {
  amount: (a, b) => {
    const av = a.fields.amount?.value;
    const bv = b.fields.amount?.value;
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return bv - av;
  },
  qty: (a, b) => {
    const av = a.fields.sku_qty?.value;
    const bv = b.fields.sku_qty?.value;
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    return bv - av;
  },
  name: (a, b) => (a.fields.name?.value || "").localeCompare(b.fields.name?.value || "", "th"),
  dept: (a, b) => (a.department || "").localeCompare(b.department || "", "th"),
};

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

  // Focus Items: same date/Division-scoped rows the product list below
  // uses, narrowed to the LP watch-list criteria - computed once per
  // render (not per keystroke, nothing here depends on the search box).
  const focusRows = filteredRows
    .map((p) => ({ product: p, reasons: focusItemReasons(p) }))
    .filter((f) => f.reasons.length > 0)
    .sort((a, b) => (b.product.fields?.amount?.value ?? -1) - (a.product.fields?.amount?.value ?? -1));

  // Product-list's own local search box (spec section 13-14) - see
  // localSearchText/localDeptFilter/sortKey above for why this doesn't
  // trigger a full re-render on every keystroke: applySearch() is called
  // fresh inside drawTable() below, not baked into this outer render.
  const productDepartments = [...new Set(filteredRows.map((p) => p.department).filter(Boolean))].sort();
  function applySearch(rows) {
    const q = localSearchText.trim().toLowerCase();
    return rows.filter((p) => {
      if (localDeptFilter && p.department !== localDeptFilter) return false;
      if (!q) return true;
      return (p._search || "").includes(q);
    });
  }

  // Preserve the search box's cursor/focus across the innerHTML rebuild
  // below - same fix as products.js for the same class of bug (an
  // unrelated background render must not kick focus out of the box).
  const searchInputEl = container.querySelector("#dashProductSearch");
  const hadFocus = searchInputEl === document.activeElement;
  const selectionStart = hadFocus ? searchInputEl.selectionStart : null;

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Dashboard</div>
      <div class="workspace-sub">สรุปสินค้าที่เข้า อ้างอิงวันที่ในเอกสาร</div>
    </div>

    <div id="dashStatusStrip"></div>

    <div class="dash-filters">
      <div class="dash-filter">
        <label for="dashDateFrom">จาก</label>
        <input type="date" id="dashDateFrom" value="${escapeHtml(dashboardDateFrom)}" />
        <span class="dash-filter-dmy">${fmtDateDMY(dashboardDateFrom)}</span>
      </div>
      <div class="dash-filter">
        <label for="dashDateTo">ถึง</label>
        <input type="date" id="dashDateTo" value="${escapeHtml(dashboardDateTo)}" />
        <span class="dash-filter-dmy">${fmtDateDMY(dashboardDateTo)}</span>
      </div>
      <div class="dash-date-shortcuts">
        ${DATE_SHORTCUTS.map((s) => `<button type="button" class="dash-date-shortcut-btn" data-shortcut="${escapeHtml(s.label)}">${escapeHtml(s.label)}</button>`).join("")}
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
        dashboardOverview ? (dashboardOverview.amountAvailable ? "฿ " + fmtBaht(dashboardOverview.totals.amount) : "ไม่มีข้อมูลมูลค่า") : "…",
        "มูลค่ารวม", icons.trendingUp, "#2563EB"
      )}
      ${kpiIconCard(dashboardOverview ? fmtNum(dashboardOverview.totals.rowCount) : "…", "จำนวนรายการ", icons.box, "#12B886")}
      ${kpiIconCard(dashboardOverview ? fmtNum(dashboardOverview.totals.documentCount) : "…", "จำนวนเอกสาร", icons.building, "#9B51E0")}
    </div>

    ${
      dashboardOverview?.isDataIncomplete
        ? `<div class="dash-reconcile-warning">
            <span class="dash-reconcile-warning-icon">⚠</span>
            <span>
              ข้อมูลสรุปไม่สมบูรณ์ - ไม่สามารถดึงสรุป Division ของ ${fmtNum(dashboardOverview.incompleteDocumentCount)} เอกสารในช่วงวันที่นี้ได้
              (จำนวนเอกสาร/จำนวนรายการด้านบนยังถูกต้อง แต่มูลค่ารวมและกราฟตาม Division อาจไม่รวมเอกสารดังกล่าว)
            </span>
          </div>`
        : ""
    }

    ${
      dashboardOverview?.unreconciledDocumentCount > 0
        ? `<div class="dash-reconcile-warning">
            <span class="dash-reconcile-warning-icon">⚠</span>
            <span>
              ${fmtNum(dashboardOverview.unreconciledDocumentCount)} เอกสารมียอดรวมที่พิมพ์ในเอกสารไม่ตรงกับผลรวมที่อ่านได้จริง (ยังไม่ผ่านการตรวจสอบยอด)
              ${dashboardOverview.amountAvailable ? ` คิดเป็นมูลค่า ฿ ${fmtBaht(dashboardOverview.unreconciledAmount)} ที่รวมอยู่ในตัวเลขด้านบน` : ""} -
              <button type="button" class="link-btn" id="dashReconcileWarningLink">ตรวจสอบเอกสาร</button>
            </span>
          </div>`
        : ""
    }

    <div class="section-title">สินค้าเฝ้าระวัง (Focus Items)${focusRows.length ? ` · ${fmtNum(focusRows.length)} รายการ` : ""}</div>
    <div class="dash-panel" id="dashFocusItemsPanel"></div>

    <div class="section-title">${dashboardOverview?.amountAvailable === false ? "จำนวนรายการตาม Division" : "มูลค่าตาม Division"}</div>
    <div class="dash-panel dash-division-value-panel" id="dashDivisionValueChart"></div>

    <div class="section-title">แผนกที่มีสินค้าเข้าเยอะสุด (ตามจำนวน)</div>
    <div class="dash-panel" id="dashDeptPiePanel">
      <div id="dashDeptPie"></div>
    </div>

    <div class="dash-product-list-head">
      <div>
        <div class="section-title" style="margin:0;">รายการสินค้าวันนี้</div>
        <div class="workspace-sub" id="dashProductListCount">${fmtNum(applySearch(filteredRows).length)} รายการ</div>
      </div>
      <div class="dash-product-list-controls">
        <input id="dashProductSearch" class="search-input" type="text" placeholder="ค้นหา Barcode / Article / ชื่อสินค้า" value="${escapeHtml(localSearchText)}" />
        <select id="dashProductDeptSelect" class="filter-chip">
          <option value="">ทุก Division / Department</option>
          ${productDepartments.map((d) => `<option value="${escapeHtml(d)}"${localDeptFilter === d ? " selected" : ""}>${escapeHtml(d)}</option>`).join("")}
        </select>
        <select id="dashProductSortSelect" class="filter-chip">
          <option value="amount"${sortKey === "amount" ? " selected" : ""}>มูลค่าสูงสุด</option>
          <option value="qty"${sortKey === "qty" ? " selected" : ""}>จำนวนสูงสุด</option>
          <option value="name"${sortKey === "name" ? " selected" : ""}>ชื่อสินค้า</option>
          <option value="dept"${sortKey === "dept" ? " selected" : ""}>แผนก</option>
        </select>
      </div>
    </div>
    <div id="dashProductsTable"></div>
    <div id="dashProductsPagination"></div>
  `;

  container.querySelector("#dashStatusStrip").innerHTML = statusStrip(documents);
  container.querySelector('[data-strip-nav="documents"]')?.addEventListener("click", () => store.navigate("documents"));
  container.querySelector('[data-strip-nav="review"]')?.addEventListener("click", () => store.navigate("review"));
  container.querySelector("#dashReconcileWarningLink")?.addEventListener("click", () => store.navigate("documents"));

  const refetch = async (patch) => {
    try {
      await store.setDashboardOverviewFilters(patch);
    } catch (error) {
      store.set({
        errorDialog: {
          title: "โหลดข้อมูลสรุปไม่สำเร็จ",
          message: String(error?.message || error),
          diagnosticId: error?.diagnosticId,
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
  container.querySelectorAll(".dash-date-shortcut-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const shortcut = DATE_SHORTCUTS.find((s) => s.label === btn.dataset.shortcut);
      const [dateFrom, dateTo] = shortcut.range();
      refetch({ dateFrom, dateTo });
    });
  });

  renderFocusItemsPanel(container.querySelector("#dashFocusItemsPanel"), focusRows, (row) => {
    store.openPanel({ type: "product", rowId: row.rowId, data: row });
  });

  renderDivisionValueChart(container.querySelector("#dashDivisionValueChart"), dashboardOverview, departmentsByDivision, (depts, name) => {
    store.navigate("products", { deptFilter: depts, deptFilterLabel: name });
  });

  renderDepartmentBarChart(container.querySelector("#dashDeptPie"), filteredRows);

  const tableHost = container.querySelector("#dashProductsTable");
  const paginationHost = container.querySelector("#dashProductsPagination");
  const countEl = container.querySelector("#dashProductListCount");

  // Re-applies search/dept-filter/sort fresh from filteredRows (already
  // computed once above from the date-range/Division header filter) on
  // every call - typing in the search box or changing sort only re-runs
  // this and repaints the table/pagination/count label, never the whole
  // Dashboard (KPIs, Division value chart, department chart all stay
  // untouched), so it stays cheap even with tens of thousands of rows.
  function drawTable() {
    const searchedRows = applySearch(filteredRows);
    countEl.textContent = `${fmtNum(searchedRows.length)} รายการ`;
    const sortedRows = [...searchedRows].sort(SORT_COMPARATORS[sortKey]);
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

  const searchInput = container.querySelector("#dashProductSearch");
  if (hadFocus) {
    searchInput.focus();
    searchInput.setSelectionRange(selectionStart, selectionStart);
  }
  let searchDebounce = null;
  searchInput.addEventListener("input", (e) => {
    localSearchText = e.target.value;
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => { page = 1; drawTable(); }, 200);
  });
  container.querySelector("#dashProductDeptSelect").addEventListener("change", (e) => {
    localDeptFilter = e.target.value;
    page = 1;
    drawTable();
  });
  container.querySelector("#dashProductSortSelect").addEventListener("change", (e) => {
    sortKey = e.target.value;
    page = 1;
    drawTable();
  });
}
