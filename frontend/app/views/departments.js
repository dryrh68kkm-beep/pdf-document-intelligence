function fmtNum(n) {
  return (n ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

export function renderDepartments(container, store) {
  const { dashboard } = store.state;
  container.innerHTML = `<div class="workspace-header"><div class="workspace-title">Departments</div><div class="workspace-sub">${dashboard?.departmentCount ?? 0} แผนก</div></div><div class="dept-grid" id="deptGrid"></div>`;
  const grid = container.querySelector("#deptGrid");
  (dashboard?.departments || []).forEach((d) => {
    const card = document.createElement("div");
    card.className = "dept-card";
    card.innerHTML = `
      <div class="dept-card-head">
        <span class="dept-card-name">${d.name}</span>
        ${d.reviewCount > 0 ? `<span class="dept-card-badge warn">${d.reviewCount} ต้องตรวจสอบ</span>` : `<span class="dept-card-badge">✓</span>`}
      </div>
      <div class="dept-card-stat">${d.skuCount} SKU · ${d.rowCount} รายการ</div>
      <div class="dept-card-stat">น้ำหนัก ${fmtNum(d.totals.weight_qty)} กก. · PU ${fmtNum(d.totals.pu_qty)} · SKU qty ${fmtNum(d.totals.sku_qty)}</div>
    `;
    card.addEventListener("click", () => store.navigate("products", { deptFilter: d.name }));
    grid.appendChild(card);
  });
}
