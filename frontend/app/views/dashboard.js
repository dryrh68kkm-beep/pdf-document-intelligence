const DIVISION_COLORS = ["#3478f6", "#2db486", "#ffb329", "#9560d8", "#ef6570", "#4d91a8"];

function fmtNum(value) {
  return (value ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 0 });
}

function fmtBaht(value) {
  return (value ?? 0).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function divisionColor(index) {
  return DIVISION_COLORS[index % DIVISION_COLORS.length];
}

function buildDonut(divisions, amountAvailable) {
  const total = divisions.reduce((sum, division) => sum + (division.amount || 0), 0);
  if (!amountAvailable || total <= 0) {
    return { background: "#edf1f7", total, percentages: new Map() };
  }

  let cursor = 0;
  const stops = [];
  const percentages = new Map();
  divisions.forEach((division, index) => {
    const percentage = (division.amount / total) * 100;
    const next = cursor + percentage;
    percentages.set(division.divisionCode, percentage);
    if (percentage > 0) {
      stops.push(`${divisionColor(index)} ${cursor.toFixed(3)}% ${next.toFixed(3)}%`);
    }
    cursor = next;
  });

  return {
    background: stops.length ? `conic-gradient(${stops.join(",")})` : "#edf1f7",
    total,
    percentages,
  };
}

function kpi(icon, label, value, unit = "") {
  return `
    <div class="phase4-kpi">
      <div class="phase4-kpi-icon" aria-hidden="true">${icon}</div>
      <div>
        <div class="phase4-kpi-label">${label}</div>
        <div class="phase4-kpi-value">${value}${unit ? `<span class="phase4-kpi-unit">${unit}</span>` : ""}</div>
      </div>
    </div>`;
}

function dateBounds(documents) {
  const dates = documents
    .filter((document) => document.status === "complete" && document.documentDate)
    .map((document) => document.documentDate)
    .sort();
  return { min: dates[0] || "", max: dates[dates.length - 1] || "" };
}

export function renderDashboard(container, store) {
  const {
    documents,
    dashboardOverview,
    dashboardDateFrom,
    dashboardDateTo,
    dashboardDivisionFilter,
  } = store.state;

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

  const bounds = dateBounds(documents);
  const overview = dashboardOverview;
  const divisions = overview?.divisions || [];
  const divisionOptions = divisions
    .map((division) => `<option value="${escapeHtml(division.divisionCode)}"${dashboardDivisionFilter === division.divisionCode ? " selected" : ""}>${escapeHtml(division.divisionCode)} - ${escapeHtml(division.divisionName)}</option>`)
    .join("");

  container.innerHTML = `
    <div class="phase4-dashboard">
      <div class="phase4-head">
        <div>
          <div class="phase4-title">Dashboard</div>
          <div class="phase4-subtitle">สรุปภาพรวมข้อมูล โดยอ้างอิงวันที่ที่อ่านได้จากเอกสาร</div>
        </div>
        <div class="phase4-filters">
          <div class="phase4-filter">
            <label for="phase4DateFrom">จาก</label>
            <input id="phase4DateFrom" type="date" value="${escapeHtml(dashboardDateFrom)}" min="${escapeHtml(bounds.min)}" max="${escapeHtml(bounds.max)}">
            <span>–</span>
            <label for="phase4DateTo">ถึง</label>
            <input id="phase4DateTo" type="date" value="${escapeHtml(dashboardDateTo)}" min="${escapeHtml(bounds.min)}" max="${escapeHtml(bounds.max)}">
          </div>
          <div class="phase4-filter">
            <label for="phase4Division">Division</label>
            <select id="phase4Division">
              <option value="all"${dashboardDivisionFilter === "all" ? " selected" : ""}>ทั้งหมด</option>
              ${divisionOptions}
            </select>
          </div>
        </div>
      </div>
      <div id="phase4Content"></div>
    </div>`;

  const applyFilters = () => {
    const dateFrom = container.querySelector("#phase4DateFrom")?.value || "";
    const dateTo = container.querySelector("#phase4DateTo")?.value || "";
    const division = container.querySelector("#phase4Division")?.value || "all";
    store.setDashboardOverviewFilters({ dateFrom, dateTo, division });
  };
  container.querySelector("#phase4DateFrom")?.addEventListener("change", applyFilters);
  container.querySelector("#phase4DateTo")?.addEventListener("change", applyFilters);
  container.querySelector("#phase4Division")?.addEventListener("change", applyFilters);

  const content = container.querySelector("#phase4Content");
  if (!overview) {
    content.innerHTML = `<div class="phase4-panel phase4-empty"><strong>กำลังสรุปข้อมูล</strong><span>กำลังรวมข้อมูลตามวันที่ในเอกสาร...</span></div>`;
    return;
  }

  if (overview.totals.documentCount === 0) {
    content.innerHTML = `
      <div class="phase4-panel phase4-empty">
        <strong>ไม่พบเอกสารในช่วงที่เลือก</strong>
        <span>ตัวกรองนี้ใช้วันที่ที่อ่านได้จาก PDF เท่านั้น</span><br>
        <button class="btn" id="phase4ClearFilters" style="margin-top:14px;">ล้างตัวกรอง</button>
      </div>`;
    content.querySelector("#phase4ClearFilters")?.addEventListener("click", () => {
      store.setDashboardOverviewFilters({ dateFrom: "", dateTo: "", division: "all" });
    });
    return;
  }

  const donut = buildDonut(divisions, overview.amountAvailable);
  const visibleRows = dashboardDivisionFilter === "all"
    ? divisions
    : divisions.filter((division) => division.divisionCode === dashboardDivisionFilter);
  const selectedShare = dashboardDivisionFilter === "all"
    ? 100
    : donut.percentages.get(dashboardDivisionFilter) || 0;

  const kpis = [
    kpi("฿", "มูลค่ารวม", overview.amountAvailable ? fmtBaht(overview.totals.amount) : "—", overview.amountAvailable ? "บาท" : ""),
    kpi("▤", "จำนวนรายการ", fmtNum(overview.totals.rowCount), "รายการ"),
    kpi("▧", "จำนวนเอกสาร", fmtNum(overview.totals.documentCount), "เอกสาร"),
  ].join("");

  const legendRows = divisions.map((division, index) => {
    const percentage = donut.percentages.get(division.divisionCode) || 0;
    return `
      <div class="phase4-legend-row">
        <div class="phase4-legend-name">
          <span class="phase4-dot" style="background:${divisionColor(index)}"></span>
          <span>${escapeHtml(division.divisionCode)} - ${escapeHtml(division.divisionName)}</span>
        </div>
        <div class="phase4-money">${overview.amountAvailable ? fmtBaht(division.amount) : "—"}</div>
        <div class="phase4-percent">${overview.amountAvailable ? `${percentage.toFixed(1)}%` : "—"}</div>
      </div>`;
  }).join("");

  const tableRows = visibleRows.map((division, index) => {
    const originalIndex = divisions.findIndex((item) => item.divisionCode === division.divisionCode);
    const percentage = donut.percentages.get(division.divisionCode) || 0;
    return `
      <tr data-division="${escapeHtml(division.divisionCode)}" title="กรอง Dashboard เป็น ${escapeHtml(division.divisionName)}">
        <td>
          <span class="phase4-dot" style="display:inline-block;margin-right:8px;background:${divisionColor(originalIndex >= 0 ? originalIndex : index)}"></span>
          ${escapeHtml(division.divisionCode)} - ${escapeHtml(division.divisionName)}
        </td>
        <td class="num">${overview.amountAvailable ? fmtBaht(division.amount) : "—"}</td>
        <td class="num">${overview.amountAvailable ? `${percentage.toFixed(1)}%` : "—"}</td>
        <td class="num">${fmtNum(division.rowCount)}</td>
        <td class="num">${fmtNum(division.documentCount)}</td>
      </tr>`;
  }).join("");

  content.innerHTML = `
    <div class="phase4-kpis">${kpis}</div>

    <section class="phase4-panel">
      <div class="phase4-panel-title">สัดส่วนมูลค่าตาม Division</div>
      <div class="phase4-share">
        <div class="phase4-donut-wrap">
          <div class="phase4-donut" style="background:${donut.background}" role="img" aria-label="สัดส่วนมูลค่าตาม Division">
            <div class="phase4-donut-center">
              <span>มูลค่ารวม</span>
              <strong>${overview.amountAvailable ? fmtBaht(donut.total) : "—"}</strong>
              <span>${overview.amountAvailable ? "บาท" : "ยังไม่มีข้อมูลมูลค่า"}</span>
            </div>
          </div>
        </div>
        <div class="phase4-legend">${legendRows}</div>
      </div>
    </section>

    <section class="phase4-panel">
      <div class="phase4-panel-title">สรุปมูลค่าตาม Division</div>
      <div class="phase4-table-wrap">
        <table class="phase4-table">
          <thead>
            <tr>
              <th>Division</th>
              <th class="num">มูลค่า (บาท)</th>
              <th class="num">สัดส่วน</th>
              <th class="num">จำนวนรายการ</th>
              <th class="num">จำนวนเอกสาร</th>
            </tr>
          </thead>
          <tbody>
            ${tableRows}
            <tr class="total">
              <td>รวม</td>
              <td class="num">${overview.amountAvailable ? fmtBaht(overview.totals.amount) : "—"}</td>
              <td class="num">${overview.amountAvailable ? `${selectedShare.toFixed(1)}%` : "—"}</td>
              <td class="num">${fmtNum(overview.totals.rowCount)}</td>
              <td class="num">${fmtNum(overview.totals.documentCount)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div class="phase4-footnote">* ข้อมูลอ้างอิงจากวันที่ในเอกสาร ไม่ใช่วันที่อัปโหลด</div>`;

  content.querySelectorAll("tr[data-division]").forEach((row) => {
    row.addEventListener("click", () => {
      store.setDashboardOverviewFilters({ division: row.dataset.division });
    });
  });
}
