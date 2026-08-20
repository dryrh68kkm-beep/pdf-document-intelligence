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

function statusLabel(status) {
  return { complete: "ประมวลผลสำเร็จ", processing: "กำลังประมวลผล", error: "ผิดพลาด" }[status] || status;
}

function kpiCard(value, label) {
  return `<div class="kpi-card"><div class="kpi-value">${value}</div><div class="kpi-label">${label}</div></div>`;
}

function divisionCard(d, index) {
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
      <div class="division-card-amount">${fmtBaht(d.amount)}</div>
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

function divisionChart(divisions) {
  const metricKey = chartMetric === "amount" ? "amount" : "skuQty";
  const sorted = [...divisions].sort((a, b) => b[metricKey] - a[metricKey]);
  const max = Math.max(1, ...sorted.map((d) => d[metricKey]));
  const rows = sorted
    .map((d) => {
      const pct = Math.max(2, (d[metricKey] / max) * 100);
      const valueLabel = chartMetric === "amount" ? fmtBaht(d.amount) : fmtNum(d.skuQty);
      const title = `${d.divisionName} · รายการ ${fmtNum(d.rowCount)} · น้ำหนัก ${fmtNum(d.weight)} กก. · PU ${fmtNum(d.puQty)} · SKU ${fmtNum(d.skuQty)} · มูลค่ารวม ${fmtBaht(d.amount)}`;
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
          <button class="sort-btn${chartMetric === "sku" ? " active" : ""}" data-metric="sku">SKU</button>
          <button class="sort-btn${chartMetric === "amount" ? " active" : ""}" data-metric="amount">มูลค่า ฿</button>
        </span>
      </div>
      <div class="bar-chart">${rows}</div>
    </div>`;
}

export function renderDashboard(container, store) {
  const { documents, currentDocumentId, divisionSummary } = store.state;
  const doc = documents.find((d) => d.id === currentDocumentId);

  if (!doc) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="icon">📦</div>
        <div class="title">ยังไม่มีเอกสาร</div>
        <div>เพิ่ม PDF เพื่อเริ่มวิเคราะห์</div>
        <button class="btn btn-primary" style="margin-top:14px;" id="emptyAddBtn">＋ Add Files</button>
      </div>`;
    container.querySelector("#emptyAddBtn").addEventListener("click", () => document.getElementById("fileInput").click());
    return;
  }

  const header = `
    <div class="doc-header">
      <div class="doc-header-info">
        <div class="doc-header-title">${doc.filename}</div>
        <div class="doc-header-meta">
          <span>${fmtDate(doc.uploadedAt)}</span>
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

  const kpis = [
    kpiCard(fmtNum(divisionSummary.documentTotals.rowCount), "รายการทั้งหมด"),
    kpiCard(fmtNum(divisionSummary.documentTotals.weight), "น้ำหนักรวม (กก.)"),
    kpiCard(fmtNum(divisionSummary.documentTotals.puQty), "PU รวม"),
    kpiCard(fmtNum(divisionSummary.documentTotals.skuQty), "SKU รวม"),
    kpiCard(fmtBaht(divisionSummary.documentTotals.amount), "มูลค่ารวม (฿)"),
  ].join("");

  const divisionCards = divisionSummary.divisions.map((d, i) => divisionCard(d, i)).join("");
  const chart = divisionChart(divisionSummary.divisions);

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
      ${dq.unmappedRowCount ? `<div class="dq-row"><span>Unmapped amount</span><span class="mono">${fmtBaht(dq.unmappedAmount)}</span></div>` : ""}
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
