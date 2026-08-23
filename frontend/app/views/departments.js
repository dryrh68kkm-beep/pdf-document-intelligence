function fmtNum(n) {
  return (n ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 2 });
}

let searchQuery = "";
let currentSort = "sku";

const SORTS = {
  sku: (a, b) => b.skuCount - a.skuCount,
  rows: (a, b) => b.rowCount - a.rowCount,
  review: (a, b) => b.reviewCount - a.reviewCount,
  name: (a, b) => a.name.localeCompare(b.name),
};
const SORT_LABELS = { sku: "SKU", rows: "รายการ", review: "ต้องตรวจสอบ", name: "ชื่อ" };

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

function matchesSearch(d, q) {
  if (!q) return true;
  return `${d.name} ${d.majorDepartment || ""}`.toLowerCase().includes(q);
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
  const allDepartments = dashboard?.departments || [];

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Departments</div>
      <div class="workspace-sub">${allDepartments.length} แผนก</div>
    </div>
    <div class="filter-bar" style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px;">
      <input class="search-input" id="deptSearch" type="search" placeholder="ค้นหาแผนก..." value="${searchQuery}">
      <span class="sort-controls" style="margin-left:0;">
        เรียงตาม:
        ${Object.entries(SORT_LABELS)
          .map(([key, label]) => `<button class="sort-btn${key === currentSort ? " active" : ""}" data-sort="${key}">${label}</button>`)
          .join("")}
      </span>
    </div>
    <div id="deptRoot"></div>
  `;

  container.querySelector("#deptSearch").addEventListener("input", (e) => {
    searchQuery = e.target.value;
    renderDepartments(container, store);
    const input = container.querySelector("#deptSearch");
    input?.focus();
    input?.setSelectionRange(searchQuery.length, searchQuery.length);
  });
  container.querySelectorAll(".sort-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentSort = btn.dataset.sort;
      renderDepartments(container, store);
    });
  });

  const root = container.querySelector("#deptRoot");
  const q = searchQuery.trim().toLowerCase();
  const visible = allDepartments.filter((d) => matchesSearch(d, q));

  if (!allDepartments.length) {
    root.innerHTML = `<div class="empty-state"><div class="icon">🏷️</div><div class="title">ยังไม่มีข้อมูลแผนก</div><div>เพิ่ม PDF เพื่อเริ่มวิเคราะห์</div></div>`;
    return;
  }
  if (!visible.length) {
    root.innerHTML = `<div class="empty-state"><div class="icon">🔎</div><div class="title">ไม่พบแผนกที่ตรงกับคำค้นหา</div></div>`;
    return;
  }

  const groups = new Map();
  for (const d of visible) {
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
    [...members].sort(SORTS[currentSort]).forEach((m) => subgrid.appendChild(deptCard(m, store)));
    group.appendChild(subgrid);
    root.appendChild(group);
  }

  if (ungrouped.length) {
    const grid = document.createElement("div");
    grid.className = "dept-grid";
    [...ungrouped].sort(SORTS[currentSort]).forEach((d) => grid.appendChild(deptCard(d, store)));
    root.appendChild(grid);
  }
}
