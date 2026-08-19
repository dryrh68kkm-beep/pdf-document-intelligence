function kpiCard(value, label, cls = "") {
  return `<div class="kpi-card"><div class="kpi-value ${cls}">${value}</div><div class="kpi-label">${label}</div></div>`;
}

function fmtNum(n) {
  return n.toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

export function renderDashboard(container, store) {
  const { dashboard, documents } = store.state;

  if (!dashboard || dashboard.completedCount === 0) {
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

  const kpis = [
    kpiCard(dashboard.rowCount.toLocaleString(), "สินค้าเข้า"),
    kpiCard(dashboard.skuCount.toLocaleString(), "SKU"),
    kpiCard(dashboard.departmentCount, "แผนก"),
    kpiCard(dashboard.reviewCount, "ต้องตรวจสอบ", dashboard.reviewCount > 0 ? "warn" : "ok"),
    ...(dashboard.nonProductCount > 0 ? [kpiCard(dashboard.nonProductCount, "ของแถม/ไม่ใช่สินค้า")] : []),
    ...dashboard.numericColumns.map((c) => kpiCard(fmtNum(dashboard.grandTotals[c.key] ?? 0), c.label)),
  ].join("");

  const maxTotal = Math.max(...dashboard.departments.map((d) => d.totals.sku_qty || 0), 1);
  const bars = dashboard.departments
    .slice(0, 8)
    .map((d) => {
      const val = d.totals.sku_qty || 0;
      const pct = Math.max(4, Math.round((val / maxTotal) * 100));
      return `
        <div class="bar-row">
          <div>${d.name}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
          <div class="bar-value">${fmtNum(val)}</div>
        </div>`;
    })
    .join("");

  const deptCards = dashboard.departments
    .map(
      (d) => `
      <div class="dept-card" data-dept="${d.name}">
        <div class="dept-card-head">
          <span class="dept-card-name">${d.name}</span>
          ${d.reviewCount > 0 ? `<span class="dept-card-badge warn">${d.reviewCount} ต้องตรวจสอบ</span>` : `<span class="dept-card-badge">✓</span>`}
        </div>
        <div class="dept-card-stat">${d.skuCount} SKU · ${fmtNum(d.totals.pu_qty || 0)} PU</div>
        <div class="dept-card-stat">น้ำหนัก ${fmtNum(d.totals.weight_qty || 0)} กก. · SKU qty ${fmtNum(d.totals.sku_qty || 0)}</div>
      </div>`
    )
    .join("");

  const processing = documents.filter((d) => d.status === "processing");
  const processingBanner = processing.length
    ? `<div class="workspace-sub" style="margin-bottom:14px;">⏳ กำลังประมวลผล ${processing.length} ไฟล์ — ข้อมูลจะอัปเดตอัตโนมัติ</div>`
    : "";

  const coverage = (dashboard.masterCoverage || [])
    .map((c) => `<span class="kpi-coverage-chip">${c.label} <b>${c.percent}%</b></span>`)
    .join("");

  container.innerHTML = `
    ${processingBanner}
    <div class="kpi-row">${kpis}</div>
    ${coverage ? `<div class="section-title">Master Coverage</div><div class="kpi-coverage-row">${coverage}</div>` : ""}
    <div class="section-title">ยอดตามแผนก (เรียงตาม SKU qty)</div>
    <div class="bar-chart">${bars}</div>
    <div class="section-title">ทุกแผนก</div>
    <div class="dept-grid">${deptCards}</div>
  `;

  container.querySelectorAll(".dept-card").forEach((el) => {
    el.addEventListener("click", () => store.navigate("products", { deptFilter: el.dataset.dept }));
  });
}
