import { icons } from "../icons.js";

// Executive Overview: everything on this page is token-driven (styles.css)
// and reads only data the backend already computes - aggregate.py's
// build_dashboard_state() and divisions.py's build_division_summary(), both
// of which are the single source of truth the app already relies on
// elsewhere. No new backend call is introduced here.

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

function divisionColor(index) {
  return `var(${DIVISION_VARS[index % DIVISION_VARS.length]})`;
}

function fmtNum(value) {
  return (value ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 0 });
}

function fmtBaht(value) {
  return (value ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtDate(value) {
  if (!value) return "ไม่พบวันที่เอกสาร";
  return new Date(`${value}T00:00:00`).toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" });
}

function documentTypeLabel(documentType) {
  return DOCUMENT_TYPE_LABEL[documentType] || "ไม่ทราบประเภท";
}

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

function recentDocumentRow(doc, store, isCurrent) {
  const reviewCount = doc.qualityCounts?.needReview ?? 0;
  const statusLabel = doc.status === "complete" ? "พร้อมใช้งาน" : doc.status === "error" ? "ผิดพลาด" : "กำลังประมวลผล";
  const row = document.createElement("div");
  row.className = "recent-doc-row" + (isCurrent ? " current" : "");
  row.innerHTML = `
    <span class="status-dot ${doc.status}"></span>
    <div style="min-width:0;flex:1;">
      <div class="doc-name">${escapeHtml(doc.filename)}</div>
      <div class="doc-meta">${escapeHtml(documentTypeLabel(doc.documentType))} · ${fmtDate(doc.documentDate)} · ${statusLabel}${reviewCount ? ` · ${reviewCount} ต้องตรวจ` : ""}</div>
    </div>
    ${doc.qualityScore != null ? `<span class="band-chip band-${(QUALITY_BAND[doc.qualityBand] || {}).tone === "ok" ? "HIGH" : (QUALITY_BAND[doc.qualityBand] || {}).tone === "warn" ? "MEDIUM" : "LOW"}"><span class="dot"></span>${doc.qualityScore}</span>` : ""}
  `;
  row.addEventListener("click", () => store.selectDashboardDocument(doc.id));
  return row;
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
      <div class="workspace-title">Executive Overview</div>
    </div>

    <label class="doc-selector-label" for="dashDocSelect">เอกสารปัจจุบัน</label>
    <select class="doc-selector" id="dashDocSelect">${docOptions}</select>

    <div id="dashCurrentDoc"></div>

    <div class="section-title">ภาพรวมช่วงเวลา (ตัวกรอง)</div>
    <div class="dash-filters" id="dashFilters">
      <div class="dash-filter">
        <label for="dashDateFrom">จาก</label>
        <input id="dashDateFrom" type="date" value="${escapeHtml(dashboardDateFrom)}">
        <span>–</span>
        <label for="dashDateTo">ถึง</label>
        <input id="dashDateTo" type="date" value="${escapeHtml(dashboardDateTo)}">
      </div>
    </div>

    <div id="dashOverviewKpis"></div>

    <div class="dashboard-body">
      <div class="dashboard-main">
        <div class="section-title">Division Overview</div>
        <div id="dashDivisions"></div>

        <div class="section-title">Department Overview <span class="workspace-sub" style="text-transform:none;letter-spacing:normal;font-weight:400;">(รวมทุกเอกสาร)</span></div>
        <div id="dashDepartments" class="dept-grid"></div>

        <div class="section-title">Recent Documents</div>
        <div id="dashRecent"></div>
      </div>
      <div class="dashboard-aside">
        <div class="section-title" style="margin-top:0;">Data Quality</div>
        <div id="dashQuality"></div>

        <div class="section-title">Reconciliation Status</div>
        <div id="dashReconciliation"></div>
      </div>
    </div>
  `;

  container.querySelector("#dashDocSelect").addEventListener("change", (e) => {
    store.selectDashboardDocument(e.target.value);
  });

  const applyFilters = () => {
    const dateFrom = container.querySelector("#dashDateFrom")?.value || "";
    const dateTo = container.querySelector("#dashDateTo")?.value || "";
    store.setDashboardOverviewFilters({ dateFrom, dateTo });
  };
  container.querySelector("#dashDateFrom")?.addEventListener("change", applyFilters);
  container.querySelector("#dashDateTo")?.addEventListener("change", applyFilters);

  // ---- Current document header + quality banner ----
  const currentDocHost = container.querySelector("#dashCurrentDoc");
  if (currentDoc) {
    const statusLabel = currentDoc.status === "complete" ? "พร้อมใช้งาน" : currentDoc.status === "error" ? "ผิดพลาด" : "กำลังประมวลผล";
    currentDocHost.innerHTML = `
      <div class="doc-header">
        <div>
          <div class="doc-header-title">${escapeHtml(currentDoc.filename)}</div>
          <div class="doc-header-meta">
            <span>${escapeHtml(documentTypeLabel(currentDoc.documentType))}</span> ·
            <span>${fmtDate(currentDoc.documentDate)}</span> ·
            <span class="status-pill status-${currentDoc.status}">${statusLabel}</span>
          </div>
        </div>
      </div>
      ${qualityBanner(currentDoc)}
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
    const currentTotals = divisionSummary?.documentTotals;
    kpiHost.innerHTML = `
      <div class="kpi-row">
        ${kpiCard(fmtNum(totals.rowCount), "จำนวนรายการ (ตามช่วงเวลา)")}
        ${kpiCard(fmtNum(totals.documentCount), "จำนวนเอกสาร")}
        ${kpiCard(dashboardOverview.amountAvailable ? fmtBaht(totals.amount) : "—", "มูลค่ารวม (บาท)")}
        ${currentTotals ? kpiCard(fmtNum(currentTotals.weight), "น้ำหนักเอกสารปัจจุบัน (กก.)") : ""}
        ${currentTotals ? kpiCard(fmtNum(currentTotals.skuQty), "SKU เอกสารปัจจุบัน") : ""}
        ${kpiCard(fmtNum(dashboard?.reviewCount ?? 0), "ต้องตรวจสอบ (ทั้งหมด)", (dashboard?.reviewCount ?? 0) > 0 ? "warn" : "ok")}
      </div>`;
  }

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
        <div class="division-card-foot">คลิกเพื่อกรองภาพรวม</div>
      `;
      card.addEventListener("click", () => {
        store.setDashboardOverviewFilters({ division: dashboardDivisionFilter === division.divisionCode ? "all" : division.divisionCode });
      });
      grid.appendChild(card);
    });
    divisionsHost.innerHTML = "";
    divisionsHost.appendChild(grid);
  }

  // ---- Department Overview (workspace-wide, from /api/state) ----
  const deptHost = container.querySelector("#dashDepartments");
  const topDepartments = (dashboard?.departments || []).slice(0, 8);
  if (!topDepartments.length) {
    deptHost.innerHTML = `<div class="empty-state" style="padding:24px;grid-column:1/-1;"><div class="title">ยังไม่มีข้อมูลแผนก</div></div>`;
  } else {
    deptHost.innerHTML = "";
    topDepartments.forEach((d) => {
      const card = document.createElement("div");
      card.className = "dept-card";
      card.innerHTML = `
        <div class="dept-card-head">
          <span class="dept-card-name">${escapeHtml(d.name)}</span>
          ${d.reviewCount > 0 ? `<span class="dept-card-badge warn">${d.reviewCount} ต้องตรวจสอบ</span>` : `<span class="dept-card-badge">✓</span>`}
        </div>
        <div class="dept-card-stat">${fmtNum(d.skuCount)} SKU · ${fmtNum(d.rowCount)} รายการ</div>
      `;
      card.addEventListener("click", () => store.navigate("products", { deptFilter: d.name }));
      deptHost.appendChild(card);
    });
  }

  // ---- Data Quality panel (current document) ----
  const qualityHost = container.querySelector("#dashQuality");
  const dq = divisionSummary?.dataQuality;
  if (!dq) {
    qualityHost.innerHTML = `<div class="dq-panel"><div class="workspace-sub">ไม่มีข้อมูลคุณภาพสำหรับเอกสารนี้</div></div>`;
  } else {
    qualityHost.innerHTML = `
      <div class="dq-panel">
        <div class="dq-row"><span>รายการปกติ</span><span class="mono">${fmtNum(dq.cleanRows)}</span></div>
        <div class="dq-row"><span>ต้องตรวจสอบ</span><span class="mono">${fmtNum(dq.reviewRequired)}</span></div>
        <div class="dq-row"><span>แก้ไขแล้ว</span><span class="mono">${fmtNum(dq.corrected)}</span></div>
        <div class="dq-row"><span>อ้างอิงจาก Master</span><span class="mono">${fmtNum(dq.resolvedFromMaster)}</span></div>
        <div class="dq-row"><span>อ้างอิงจาก OCR/PDF</span><span class="mono">${fmtNum(dq.resolvedFromOcr)}</span></div>
        <div class="dq-row"><span>ยังไม่สามารถระบุได้</span><span class="mono">${fmtNum(dq.unresolved)}</span></div>
        ${dq.unmappedDepartments?.length ? `<div class="dq-unmapped">แผนกที่ไม่พบใน Division: ${dq.unmappedDepartments.map(escapeHtml).join(", ")}</div>` : ""}
      </div>`;
  }

  // ---- Reconciliation status (current document) ----
  const reconHost = container.querySelector("#dashReconciliation");
  const recon = divisionSummary?.reconciliation;
  if (!recon || recon.status == null) {
    reconHost.innerHTML = `<div class="dq-panel"><div class="workspace-sub">ยังไม่มีผลการกระทบยอด</div></div>`;
  } else {
    const passed = recon.status === "PASSED";
    reconHost.innerHTML = `
      <div class="dq-panel">
        <div class="quality-banner quality-band-${passed ? "ok" : "critical"}" style="margin-bottom:0;">
          <span class="nav-icon" aria-hidden="true">${passed ? icons.checkCircle : icons.alertCircle}</span>
          <div>
            <div class="quality-banner-label">${passed ? "กระทบยอดผ่าน" : "กระทบยอดไม่ผ่าน"}</div>
            <div class="quality-banner-sub">${fmtNum(recon.errors)} ข้อผิดพลาด</div>
          </div>
        </div>
      </div>`;
  }

  // ---- Recent documents ----
  const recentHost = container.querySelector("#dashRecent");
  const recent = [...documents]
    .sort((a, b) => String(b.documentDate || "").localeCompare(String(a.documentDate || "")))
    .slice(0, 6);
  recentHost.innerHTML = "";
  recent.forEach((doc) => recentHost.appendChild(recentDocumentRow(doc, store, doc.id === currentDoc?.id)));
}
