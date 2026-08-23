import { icons } from "../icons.js";
import { escapeHtml } from "../escape.js";

// Executive Overview / Dashboard: everything on this page is token-driven
// (styles.css) and reads only data the backend already computes -
// aggregate.py's build_dashboard_state() and divisions.py's
// build_division_summary(), both of which are the single source of truth
// the app already relies on elsewhere. No new backend call is introduced
// here. The processing/error/animated quality-banner states (qualityBanner
// below) are unchanged from the prior redesign pass - only the layout
// around them changed.

const DIVISION_VARS = ["--division-1", "--division-2", "--division-3", "--division-4", "--division-5", "--division-6"];

const QUALITY_BAND = {
  VERIFIED: { label: "เชื่อถือได้", tone: "ok" },
  GOOD: { label: "คุณภาพดี", tone: "ok" },
  NEED_REVIEW: { label: "ต้องตรวจสอบ", tone: "warn" },
  HIGH_RISK: { label: "เสี่ยงสูง", tone: "critical" },
};

const DOCUMENT_TYPE_LABEL = {
  packing_list_bigc_cdc: "Big C",
  packing_list_bpdc: "BPDC",
  UNKNOWN_LAYOUT: "ไม่ทราบประเภท",
};

const DONUT_COLORS = ["var(--accent)", "var(--warning)", "var(--purple)", "var(--success)", "var(--text-faint)"];

function divisionColor(index) {
  return `var(${DIVISION_VARS[index % DIVISION_VARS.length]})`;
}

function fmtNum(value) {
  return (value ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 0 });
}

function fmtBaht(value) {
  return (value ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(value) {
  if (!value) return "ไม่พบวันที่เอกสาร";
  return new Date(`${value}T00:00:00`).toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" });
}

function documentTypeLabel(documentType) {
  return DOCUMENT_TYPE_LABEL[documentType] || "ไม่ทราบประเภท";
}

// Unchanged since PR #42 - processing / error / scored / unscored states,
// including the animated hourglass and pulsing status dot.
function qualityBanner(doc) {
  if (!doc || doc.status === "processing") {
    const stage = doc?.progress?.stage || "กำลังเริ่มประมวลผล";
    const progressText = doc?.progress?.total ? ` (${fmtNum(doc.progress.current)}/${fmtNum(doc.progress.total)})` : "";
    return `<div class="quality-banner quality-band-processing">
      <div class="quality-banner-score processing-hourglass" role="status" aria-label="กำลังประมวลผล">⏳</div>
      <div><div class="quality-banner-label">กำลังประมวลผลเอกสาร</div><div class="quality-banner-sub">${escapeHtml(stage)}${progressText}</div></div>
    </div>`;
  }
  if (doc.status === "error") {
    return `<div class="quality-banner quality-band-critical">
      <div class="quality-banner-score">⚠️</div>
      <div><div class="quality-banner-label">อ่านไฟล์ไม่สำเร็จ</div><div class="quality-banner-sub">${escapeHtml(doc.error || "")}</div></div>
    </div>`;
  }
  if (doc.qualityScore == null) {
    return `<div class="quality-banner quality-band-unknown">
      <div class="quality-banner-score">—</div>
      <div><div class="quality-banner-label">ยังไม่มีคะแนนคุณภาพ</div><div class="quality-banner-sub">เอกสารนี้ยังไม่มีข้อมูลคุณภาพ</div></div>
    </div>`;
  }
  const band = QUALITY_BAND[doc.qualityBand] || { label: doc.qualityBand || "—", tone: "warn" };
  return `<div class="quality-banner quality-band-${band.tone}">
    <div class="quality-banner-score">${doc.qualityScore}<span>/100</span></div>
    <div>
      <div class="quality-banner-label">${escapeHtml(band.label)}</div>
      <div class="quality-banner-sub">${fmtNum(doc.qualityCounts?.verified ?? 0)} ยืนยันแล้ว · ${fmtNum(doc.qualityCounts?.needReview ?? 0)} ต้องตรวจสอบ · ${fmtNum(doc.qualityCounts?.errors ?? 0)} error</div>
    </div>
  </div>`;
}

function kpiCard(value, label, tone = "") {
  return `<div class="kpi-card"><div class="kpi-value${tone ? " " + tone : ""}">${value}</div><div class="kpi-label">${label}</div></div>`;
}

function heroFact(icon, label, value) {
  return `<div class="doc-hero-fact"><span class="doc-hero-fact-label">${icon} ${label}</span><span class="doc-hero-fact-value">${value}</span></div>`;
}

function heroKpi(value, label) {
  return `<div class="doc-hero-kpi"><div class="doc-hero-kpi-value">${value}</div><div class="doc-hero-kpi-label">${label}</div></div>`;
}

function renderDonut(host, documents) {
  const counts = new Map();
  documents.forEach((d) => {
    const label = documentTypeLabel(d.documentType);
    counts.set(label, (counts.get(label) || 0) + 1);
  });
  const entries = [...counts.entries()].sort((a, b) => b[1] - a[1]);
  const total = documents.length;

  if (!total) {
    host.innerHTML = `<div class="workspace-sub" style="padding:20px 0;text-align:center;">ยังไม่มีเอกสาร</div>`;
    return;
  }

  let offset = 0;
  const segments = entries
    .map(([label, count], i) => {
      const pct = (count / total) * 100;
      const seg = `${DONUT_COLORS[i % DONUT_COLORS.length]} ${offset}% ${offset + pct}%`;
      offset += pct;
      return seg;
    })
    .join(", ");

  host.innerHTML = `
    <div class="donut-wrap">
      <div style="width:120px;height:120px;border-radius:50%;background:conic-gradient(${segments});display:flex;align-items:center;justify-content:center;">
        <div style="width:78px;height:78px;border-radius:50%;background:var(--surface);display:flex;flex-direction:column;align-items:center;justify-content:center;">
          <div class="mono" style="font-size:20px;font-weight:700;">${total}</div>
          <div style="font-size:10.5px;color:var(--text-faint);">เอกสาร</div>
        </div>
      </div>
      <div class="donut-legend">
        ${entries
          .map(
            ([label, count], i) => `
          <div class="donut-legend-row">
            <span class="donut-legend-dot" style="background:${DONUT_COLORS[i % DONUT_COLORS.length]};"></span>
            <span class="donut-legend-name">${escapeHtml(label)}</span>
            <span class="donut-legend-count">${count} · ${Math.round((count / total) * 100)}%</span>
          </div>`
          )
          .join("")}
      </div>
    </div>
  `;
}

export function renderDashboard(container, store) {
  const {
    documents,
    currentDocumentId,
    divisionSummary,
    dashboard,
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

  const currentDoc = documents.find((d) => d.id === currentDocumentId) || documents[0];
  const docOptions = documents
    .map((d) => `<option value="${escapeHtml(d.id)}"${d.id === currentDoc?.id ? " selected" : ""}>${escapeHtml(d.filename)}</option>`)
    .join("");

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Dashboard</div>
      <div class="workspace-sub">ภาพรวมข้อมูลการประมวลผลเอกสาร</div>
    </div>

    <label class="doc-selector-label" for="dashDocSelect">เอกสารปัจจุบัน</label>
    <select class="doc-selector" id="dashDocSelect">${docOptions}</select>

    <div class="dash-filters" id="dashFilters">
      <div class="dash-filter">
        <span class="nav-icon" aria-hidden="true">${icons.calendar}</span>
        <label for="dashDateFrom">จาก</label>
        <input id="dashDateFrom" type="date" value="${escapeHtml(dashboardDateFrom)}">
        <span>–</span>
        <label for="dashDateTo">ถึง</label>
        <input id="dashDateTo" type="date" value="${escapeHtml(dashboardDateTo)}">
      </div>
    </div>

    <div id="dashHero"></div>

    <div id="dashOverviewKpis"></div>

    <div class="dash-3col">
      <div class="dash-panel">
        <div class="dash-panel-head"><span class="dash-panel-title">Data Quality</span></div>
        <div id="dashQuality"></div>
      </div>
      <div class="dash-panel">
        <div class="dash-panel-head">
          <span class="dash-panel-title">Reconciliation Summary</span>
          <span class="dash-panel-link" id="dashReconLink">ดูรายละเอียด →</span>
        </div>
        <div id="dashReconciliation"></div>
      </div>
      <div class="dash-panel">
        <div class="dash-panel-head"><span class="dash-panel-title">Document Type</span></div>
        <div id="dashDonut"></div>
      </div>
    </div>

    <div class="section-title">Division Overview</div>
    <div id="dashDivisions"></div>
  `;

  container.querySelector("#dashDocSelect").addEventListener("change", (e) => {
    store.selectDashboardDocument(e.target.value);
  });
  container.querySelector("#dashReconLink")?.addEventListener("click", () => store.navigate("departments"));

  const applyFilters = () => {
    const dateFrom = container.querySelector("#dashDateFrom")?.value || "";
    const dateTo = container.querySelector("#dashDateTo")?.value || "";
    store.setDashboardOverviewFilters({ dateFrom, dateTo });
  };
  container.querySelector("#dashDateFrom")?.addEventListener("change", applyFilters);
  container.querySelector("#dashDateTo")?.addEventListener("change", applyFilters);

  // ---- Combined current-document hero card (icon + status + facts + KPIs) ----
  const heroHost = container.querySelector("#dashHero");
  if (currentDoc) {
    const statusLabel = currentDoc.status === "complete" ? "พร้อมใช้งาน" : currentDoc.status === "error" ? "ผิดพลาด" : "กำลังประมวลผล";
    const totals = divisionSummary?.documentTotals;
    heroHost.innerHTML = `
      <div class="doc-hero">
        <div class="doc-hero-icon" aria-hidden="true">PDF</div>
        <div class="doc-hero-main">
          <div class="doc-hero-title">${escapeHtml(currentDoc.filename)}</div>
          <div class="doc-hero-status">
            <span class="status-pill status-${currentDoc.status}">${statusLabel}</span>
            ${currentDoc.qualityScore != null ? `<span>Confidence ${currentDoc.qualityScore}%</span>` : ""}
          </div>
          ${qualityBanner(currentDoc)}
          <div class="doc-hero-facts">
            ${heroFact(icons.calendar, "วันที่เอกสาร", fmtDate(currentDoc.documentDate))}
            ${heroFact(icons.file, "หน้าเอกสาร", currentDoc.pages ?? "—")}
            ${heroFact(icons.tag, "ประเภทเอกสาร", escapeHtml(documentTypeLabel(currentDoc.documentType)))}
            ${heroFact(icons.clock, "ต้องตรวจสอบ", fmtNum(currentDoc.qualityCounts?.needReview ?? 0))}
            ${heroFact(icons.checkCircle, "สถานะ", statusLabel)}
          </div>
        </div>
        ${totals
          ? `<div class="doc-hero-kpis">
              ${heroKpi(fmtNum(totals.rowCount), "รายการทั้งหมด")}
              ${heroKpi(fmtNum(totals.weight), "น้ำหนักรวม (กก.)")}
              ${heroKpi(fmtNum(totals.puQty), "PU รวม")}
              ${heroKpi(fmtNum(totals.skuQty), "SKU รวม")}
              ${heroKpi(dashboardOverview?.amountAvailable ? fmtBaht(totals.amount) : "—", "มูลค่ารวม (฿)")}
            </div>`
          : ""}
      </div>
    `;
  }

  // ---- KPI row (aggregate across the filtered date range) ----
  const kpiHost = container.querySelector("#dashOverviewKpis");
  if (!dashboardOverview) {
    kpiHost.innerHTML = `<div class="empty-state" style="padding:30px 20px;"><div class="title">กำลังสรุปข้อมูล</div></div>`;
  } else if (dashboardOverview.totals.documentCount === 0) {
    kpiHost.innerHTML = `
      <div class="empty-state" style="padding:30px 20px;">
        <div class="title">ไม่พบเอกสารในช่วงที่เลือก</div>
        <button class="btn" id="dashClearFilters" style="margin-top:10px;">ล้างตัวกรอง</button>
      </div>`;
    kpiHost.querySelector("#dashClearFilters")?.addEventListener("click", () => {
      store.setDashboardOverviewFilters({ dateFrom: "", dateTo: "" });
    });
  } else {
    const totals = dashboardOverview.totals;
    kpiHost.innerHTML = `
      <div class="kpi-row">
        ${kpiCard(fmtNum(totals.rowCount), "จำนวนรายการ (ตามช่วงเวลา)")}
        ${kpiCard(fmtNum(totals.documentCount), "จำนวนเอกสาร")}
        ${kpiCard(dashboardOverview.amountAvailable ? fmtBaht(totals.amount) : "—", "มูลค่ารวม (บาท)")}
        ${kpiCard(fmtNum(dashboard?.reviewCount ?? 0), "ต้องตรวจสอบ (ทั้งหมด)", (dashboard?.reviewCount ?? 0) > 0 ? "warn" : "ok")}
      </div>`;
  }

  // ---- Data Quality panel (current document) ----
  const qualityHost = container.querySelector("#dashQuality");
  const dq = divisionSummary?.dataQuality;
  if (!dq) {
    qualityHost.innerHTML = `<div class="workspace-sub">ไม่มีข้อมูลคุณภาพสำหรับเอกสารนี้</div>`;
  } else {
    qualityHost.innerHTML = `
      <div class="dq-row"><span>รายการปกติ</span><span class="mono">${fmtNum(dq.cleanRows)}</span></div>
      <div class="dq-row"><span>ต้องตรวจสอบ</span><span class="mono" style="color:var(--warning);">${fmtNum(dq.reviewRequired)}</span></div>
      <div class="dq-row"><span>แก้ไขแล้ว</span><span class="mono">${fmtNum(dq.corrected)}</span></div>
      <div class="dq-row"><span>อ้างอิงจาก Master</span><span class="mono" style="color:var(--accent);">${fmtNum(dq.resolvedFromMaster)}</span></div>
      <div class="dq-row"><span>อ้างอิงจาก OCR/PDF</span><span class="mono">${fmtNum(dq.resolvedFromOcr)}</span></div>
      <div class="dq-row"><span>ยังไม่สามารถระบุได้</span><span class="mono" style="color:var(--critical);">${fmtNum(dq.unresolved)}</span></div>
      ${dq.unmappedDepartments?.length ? `<div class="dq-unmapped">แผนกที่ไม่พบใน Division: ${dq.unmappedDepartments.map(escapeHtml).join(", ")}</div>` : ""}
      <div class="dash-panel-link" id="dashQualityLink" style="margin-top:8px;">ดูรายละเอียด →</div>
    `;
    qualityHost.querySelector("#dashQualityLink")?.addEventListener("click", () => store.navigate("review"));
  }

  // ---- Reconciliation Summary: each division's document coverage within
  // the current date-range overview (real, already-computed data - not a
  // fabricated pass/fail count, since the backend only computes
  // reconciliation pass/fail per-document, not per-division). ----
  const reconHost = container.querySelector("#dashReconciliation");
  const overviewDivisions = dashboardOverview?.divisions || [];
  const overviewDocCount = dashboardOverview?.totals?.documentCount || 0;
  if (!overviewDivisions.length) {
    reconHost.innerHTML = `<div class="workspace-sub">ยังไม่มีข้อมูล Division ในช่วงที่เลือก</div>`;
  } else {
    reconHost.innerHTML = overviewDivisions
      .map((d) => {
        const num = d.documentCount;
        const den = overviewDocCount;
        const pct = den > 0 ? Math.round((num / den) * 100) : null;
        return `
          <div class="recon-summary-row">
            <div class="recon-summary-head">
              <span class="recon-summary-name">${escapeHtml(d.divisionCode)} ${escapeHtml(d.divisionName)}</span>
              <span class="recon-summary-frac">${den > 0 ? `${num}/${den}` : "—"}</span>
            </div>
            <div class="recon-track"><div class="recon-fill" style="width:${pct ?? 0}%;${pct == null ? "background:var(--surface-alt);" : ""}"></div></div>
            <div class="recon-pct">${pct == null ? "—" : pct + "%"}</div>
          </div>`;
      })
      .join("");
  }

  // ---- Document Type donut ----
  renderDonut(container.querySelector("#dashDonut"), documents);

  // ---- Division Overview ----
  const divisionsHost = container.querySelector("#dashDivisions");
  const divisions = dashboardDivisionFilter === "all"
    ? (dashboardOverview?.divisions || [])
    : (dashboardOverview?.divisions || []).filter((d) => d.divisionCode === dashboardDivisionFilter);
  if (!divisions.length) {
    divisionsHost.innerHTML = `<div class="empty-state" style="padding:24px;"><div class="title">ไม่มีข้อมูล Division ในช่วงที่เลือก</div></div>`;
  } else {
    const grid = document.createElement("div");
    grid.className = "division-grid";
    (dashboardOverview?.divisions || []).forEach((division, index) => {
      if (dashboardDivisionFilter !== "all" && division.divisionCode !== dashboardDivisionFilter) return;
      const card = document.createElement("div");
      card.className = "division-card";
      card.style.setProperty("--division-accent", divisionColor(index));
      card.innerHTML = `
        <div class="division-card-head">
          <span class="division-card-code">${escapeHtml(division.divisionCode)}</span>
          <span class="division-card-name">${escapeHtml(division.divisionName)}</span>
        </div>
        <div class="division-card-amount">${dashboardOverview.amountAvailable ? fmtBaht(division.amount) + " ฿" : "—"}</div>
        <div class="division-card-stats">
          <div class="division-stat"><span class="division-stat-value">${fmtNum(division.rowCount)}</span><span class="division-stat-label">รายการ</span></div>
          <div class="division-stat"><span class="division-stat-value">${fmtNum(division.documentCount)}</span><span class="division-stat-label">เอกสาร</span></div>
        </div>
        <div class="division-card-foot">
          <span>คลิกเพื่อกรองภาพรวม</span>
          <button type="button" class="dash-panel-link division-card-departments-link">แผนกในฝ่ายนี้ →</button>
        </div>
      `;
      card.addEventListener("click", () => {
        store.setDashboardOverviewFilters({ division: dashboardDivisionFilter === division.divisionCode ? "all" : division.divisionCode });
      });
      card.querySelector(".division-card-departments-link")?.addEventListener("click", (e) => {
        e.stopPropagation();
        store.openDivision(division.divisionCode);
      });
      grid.appendChild(card);
    });
    divisionsHost.innerHTML = "";
    divisionsHost.appendChild(grid);
  }
}
