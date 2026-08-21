// Dashboard Phase 1: Division -> Department -> Product. The home page
// leads with the 6 major divisions (data/department_hierarchy.csv is the
// only source for that structure - see templates/department_groups.py
// and api/divisions.py); it never starts at Department directly.
import { api } from "../api.js";

const DIVISION_ACCENTS = ["#4a6fa5", "#5a8f7b", "#a5764a", "#8a5a9c", "#b0553f", "#3f7f9c"];

function fmtNum(n) {
  return (n ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

function fmtBaht(n) {
  return "฿" + (n ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" });
}

function fmtDocumentDate(iso) {
  if (!iso) return "ไม่พบวันที่ในเอกสาร";
  return new Date(iso + "T00:00:00").toLocaleDateString("th-TH", { year: "numeric", month: "short", day: "numeric" });
}

function statusLabel(status) {
  return { complete: "ประมวลผลสำเร็จ", processing: "กำลังประมวลผล", error: "ผิดพลาด" }[status] || status;
}

function kpiCard(value, label) {
  return `<div class="kpi-card"><div class="kpi-value">${value}</div><div class="kpi-label">${label}</div></div>`;
}

function divisionCard(d, index, hasAmountData) {
  const accent = DIVISION_ACCENTS[index % DIVISION_ACCENTS.length];
  const statusBadge =
    d.status === "REVIEW"
      ? `<span class="dept-card-badge warn">${d.reviewCount} ต้องตรวจสอบ</span>`
      : `<span class="dept-card-badge">ปกติ</span>`;
  return `
    <div class="division-card" data-division="${d.divisionCode}" style="--division-accent:${accent}">
      <div class="division-card-head">
        <span class="division-card-code">${d.divisionCode}</span>
        <span class="division-card-name">${d.divisionName}</span>
        ${statusBadge}
      </div>
      ${hasAmountData ? `<div class="division-card-amount">${fmtBaht(d.amount)}</div>` : ""}
      <div class="division-card-stats">
        <div class="division-stat"><span class="division-stat-value">${fmtNum(d.rowCount)}</span><span class="division-stat-label">รายการ</span></div>
        <div class="division-stat"><span class="division-stat-value">${fmtNum(d.weight)}</span><span class="division-stat-label">น้ำหนัก (กก.)</span></div>
        <div class="division-stat"><span class="division-stat-value">${fmtNum(d.puQty)}</span><span class="division-stat-label">PU</span></div>
        <div class="division-stat"><span class="division-stat-value">${fmtNum(d.skuQty)}</span><span class="division-stat-label">SKU</span></div>
      </div>
      <div class="division-card-foot">${d.departmentCount} แผนก</div>
    </div>`;
}

let chartMetric = "sku";

function divisionChart(divisions, hasAmountData) {
  const activeMetric = hasAmountData ? chartMetric : "sku";
  const metricKey = activeMetric === "amount" ? "amount" : "skuQty";
  const sorted = [...divisions].sort((a, b) => b[metricKey] - a[metricKey]);
  const max = Math.max(1, ...sorted.map((d) => d[metricKey]));
  const rows = sorted
    .map((d) => {
      const pct = Math.max(2, (d[metricKey] / max) * 100);
      const valueLabel = activeMetric === "amount" ? fmtBaht(d.amount) : fmtNum(d.skuQty);
      const amountText = hasAmountData ? ` · มูลค่ารวม ${fmtBaht(d.amount)}` : "";
      const title = `${d.divisionName} · รายการ ${fmtNum(d.rowCount)} · น้ำหนัก ${fmtNum(d.weight)} กก. · PU ${fmtNum(d.puQty)} · SKU ${fmtNum(d.skuQty)}${amountText}`;
      return `
        <div class="bar-row" title="${title}">
          <span>${d.divisionCode} ${d.divisionName}</span>
          <span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span></span>
          <span class="mono">${valueLabel}</span>
        </div>`;
    })
    .join("");
  return `
    <div class="chart-panel">
      <div class="section-title chart-title-row">
        <span>ภาพรวม 6 ฝ่ายใหญ่</span>
        <span class="chart-toggle">
          <button class="sort-btn${activeMetric === "sku" ? " active" : ""}" data-metric="sku">SKU</button>
          ${hasAmountData ? `<button class="sort-btn${activeMetric === "amount" ? " active" : ""}" data-metric="amount">มูลค่า ฿</button>` : ""}
        </span>
      </div>
      <div class="bar-chart">${rows}</div>
    </div>`;
}

export function renderDashboard(container, store) {
  const { documents, currentDocumentId, divisionSummary, dashboardDateFilter } = store.state;
  const visibleDocuments = dashboardDateFilter
    ? documents.filter((item) => item.documentDate === dashboardDateFilter)
    : documents;
  const doc = visibleDocuments.find((item) => item.id === currentDocumentId);

  if (!doc) {
    const noDocuments = documents.length === 0;
    container.innerHTML = noDocuments
      ? `<div class="empty-state"><div class="icon">📦</div><div class="title">ยังไม่มีเอกสาร</div><div>เพิ่ม PDF เพื่อเริ่มวิเคราะห์</div><button class="btn btn-primary" style="margin-top:14px;" id="emptyAddBtn">＋ Add Files</button></div>`
      : `<div class="empty-state"><div class="icon">📅</div><div class="title">ไม่พบเอกสารสำหรับวันที่เลือก</div><div>ระบบกรองจากวันที่ที่อ่านได้ใน PDF เท่านั้น</div><button class="btn" style="margin-top:14px;" id="clearDateFilterBtn">ล้างตัวกรองวันที่</button></div>`;
    if (noDocuments) {
      container.querySelector("#emptyAddBtn").addEventListener("click", () => document.getElementById("fileInput").click());
    } else {
      container.querySelector("#clearDateFilterBtn").addEventListener("click", () => store.setDashboardDateFilter(""));
    }
    return;
  }

  const documentOptions = visibleDocuments
    .map((item) => `<option value="${item.id}"${item.id === currentDocumentId ? " selected" : ""}>${item.filename}</option>`)
    .join("");

  const header = `
    <div class="doc-header">
      <div class="doc-header-info">
        <label class="doc-selector-label" for="dashDocumentDateFilter">กรองจากวันที่ในเอกสาร</label>
        <input class="doc-date-filter" id="dashDocumentDateFilter" type="date" value="${dashboardDateFilter}">
        <label class="doc-selector-label" for="dashDocumentSelect">เอกสารที่กำลังดู</label>
        <select class="doc-selector" id="dashDocumentSelect">${documentOptions}</select>
        <div class="doc-header-title">${doc.filename}</div>
        <div class="doc-header-meta">
          <span>วันที่เอกสาร: ${fmtDocumentDate(doc.documentDate)}</span>
          ${doc.documentDateEvidence ? `<span>·</span><span>${doc.documentDateEvidence.label} หน้า ${doc.documentDateEvidence.page}</span>` : ""}
          <span>·</span>
          <span>${doc.pages ?? "—"} หน้า</span>
          <span>·</span>
          <span class="status-pill status-${doc.status}">${statusLabel(doc.status)}</span>
        </div>
      </div>
      <div class="doc-header-actions">
        <button class="btn" id="dashRefreshBtn">↻ Refresh</button>
        <button class="btn btn-primary" id="dashExportBtn">Export Excel</button>
      </div>
    </div>
  `;

  container.innerHTML = header;
  container.querySelector("#dashExportBtn").addEventListener("click", () => {
    window.location.href = api.exportUrl();
  });
  container.querySelector("#dashRefreshBtn").addEventListener("click", () => store.refreshAll());
  container.querySelector("#dashDocumentSelect").addEventListener("change", (event) => {
    store.selectDashboardDocument(event.target.value);
  });
  container.querySelector("#dashDocumentDateFilter").addEventListener("change", (event) => {
    store.setDashboardDateFilter(event.target.value);
  });

  if (doc.status !== "complete" || !divisionSummary) {
    const body = document.createElement("div");
    body.className = "empty-state";
    body.innerHTML =
      doc.status === "error"
        ? `<div class="icon">⚠️</div><div class="title">อ่านไฟล์ไม่สำเร็จ</div><div>${doc.error || ""}</div>`
        : `<div class="icon">⏳</div><div class="title">กำลังประมวลผลเอกสาร</div><div>${doc.progress?.stage || ""}</div>`;
    container.appendChild(body);
    return;
  }

  const hasAmountData = Boolean(divisionSummary.amountAvailable);
  const kpis = [
    kpiCard(fmtNum(divisionSummary.documentTotals.rowCount), "รายการทั้งหมด"),
    kpiCard(fmtNum(divisionSummary.documentTotals.weight), "น้ำหนักรวม (กก.)"),
    kpiCard(fmtNum(divisionSummary.documentTotals.puQty), "PU รวม"),
    kpiCard(fmtNum(divisionSummary.documentTotals.skuQty), "SKU รวม"),
    ...(hasAmountData ? [kpiCard(fmtBaht(divisionSummary.documentTotals.amount), "มูลค่ารวม (฿)")] : []),
  ].join("");

  const divisionCards = divisionSummary.divisions.map((d, i) => divisionCard(d, i, hasAmountData)).join("");
  const chart = divisionChart(divisionSummary.divisions, hasAmountData);

  const dq = divisionSummary.dataQuality;
  const rec = divisionSummary.reconciliation;
  const dqRow = (label, value) => `<div class="dq-row"><span>${label}</span><span class="mono">${fmtNum(value)}</span></div>`;
  const dataQuality = `
    <div class="dq-panel">
      <div class="section-title">Data Quality</div>
      ${dqRow("Clean rows", dq.cleanRows)}
      ${dqRow("Review required", dq.reviewRequired)}
      ${dqRow("Corrected", dq.corrected)}
      ${dqRow("Resolved from Master", dq.resolvedFromMaster)}
      ${dqRow("Resolved from OCR", dq.resolvedFromOcr)}
      ${dqRow("Unresolved", dq.unresolved)}
      ${dqRow("Unmapped departments", dq.unmappedDepartments.length)}
      ${dq.unmappedDepartments.length ? `<div class="dq-unmapped">${dq.unmappedDepartments.join(", ")}</div>` : ""}
      ${hasAmountData && dq.unmappedRowCount ? `<div class="dq-row"><span>Unmapped amount</span><span class="mono">${fmtBaht(dq.unmappedAmount)}</span></div>` : ""}
      <div class="section-title" style="margin-top:18px;">Reconciliation</div>
      <div class="dq-row"><span>Status</span><span class="mono">${rec.status ?? "—"}</span></div>
      <div class="dq-row"><span>Errors</span><span class="mono">${rec.errors}</span></div>
    </div>
  `;

  const body = document.createElement("div");
  body.className = "dashboard-body";
  body.innerHTML = `
    <div class="dashboard-main">
      <div class="kpi-row">${kpis}</div>
      ${chart}
      <div class="section-title">สรุปตามฝ่าย</div>
      <div class="division-grid">${divisionCards}</div>
    </div>
    <aside class="dashboard-aside">${dataQuality}</aside>
  `;
  container.appendChild(body);

  body.querySelectorAll(".division-card").forEach((el) => {
    el.addEventListener("click", () => store.openDivision(el.dataset.division));
  });

  body.querySelectorAll(".chart-toggle .sort-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      chartMetric = btn.dataset.metric;
      renderDashboard(container, store);
    });
  });
}
