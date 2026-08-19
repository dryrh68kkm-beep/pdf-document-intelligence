function fmtNum(n) {
  return (n ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

function deptCard(d, store) {
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
  return card;
}

// Groups department cards by `majorDepartment` (see
// templates/department_groups.py — a fixed, user-supplied mapping, never
// an inferred pattern). A major group with only one member is its own
// department and renders as a plain card with no group wrapper, so the
// common case (no grouping) looks exactly as before; a major group with
// several members renders as a header (combined totals) over a grid of
// its smaller sub-department cards, with the major department as the
// primary heading and each sub-department secondary underneath it.
export function renderDepartments(container, store) {
  const { dashboard } = store.state;
  container.innerHTML = `<div class="workspace-header"><div class="workspace-title">Departments</div><div class="workspace-sub">${dashboard?.departmentCount ?? 0} แผนก</div></div><div id="deptRoot"></div>`;
  const root = container.querySelector("#deptRoot");

  const groups = new Map();
  for (const d of dashboard?.departments || []) {
    const major = d.majorDepartment || d.name;
    if (!groups.has(major)) groups.set(major, []);
    groups.get(major).push(d);
  }

  const ungrouped = [];
  const majorGroups = [];
  for (const [major, members] of groups) {
    if (members.length === 1 && members[0].name === major) {
      ungrouped.push(members[0]);
    } else {
      majorGroups.push([major, members]);
    }
  }

  for (const [major, members] of majorGroups) {
    const totals = { weight_qty: 0, pu_qty: 0, sku_qty: 0 };
    let skuCount = 0, rowCount = 0, reviewCount = 0;
    for (const m of members) {
      skuCount += m.skuCount;
      rowCount += m.rowCount;
      reviewCount += m.reviewCount;
      for (const k of Object.keys(totals)) totals[k] += m.totals[k] || 0;
    }
    const group = document.createElement("div");
    group.className = "dept-group";
    group.innerHTML = `
      <div class="dept-group-head">
        <span class="dept-group-name">${major}</span>
        <span class="dept-group-stat">${skuCount} SKU · ${rowCount} รายการ${reviewCount > 0 ? ` · ${reviewCount} ต้องตรวจสอบ` : ""}</span>
      </div>
    `;
    const subgrid = document.createElement("div");
    subgrid.className = "dept-subgrid";
    members.forEach((m) => subgrid.appendChild(deptCard(m, store)));
    group.appendChild(subgrid);
    root.appendChild(group);
  }

  if (ungrouped.length) {
    const grid = document.createElement("div");
    grid.className = "dept-grid";
    ungrouped.forEach((d) => grid.appendChild(deptCard(d, store)));
    root.appendChild(grid);
  }
}
