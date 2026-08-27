import { escapeHtml } from "../escape.js";

function fmtNum(n) {
  return (n ?? 0).toLocaleString("th-TH", { maximumFractionDigits: 0 });
}

function fmtBaht(n) {
  return "฿" + (n ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Keep these exact name->color pairs aligned with Dashboard. Real master
// catalogs do not reliably use the same numeric Division codes as a mockup,
// so the user-visible Division name is the stable key in both places.
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

function identityForProduct(product) {
  return product.fields?.barcode?.value || product.fields?.article?.value || product.rowId || null;
}

function bucketFor(buckets, code, name) {
  if (!buckets.has(code)) {
    buckets.set(code, {
      divisionCode: code,
      divisionName: name,
      departmentCount: 0,
      rowCount: 0,
      reviewCount: 0,
      fallbackSkuCount: 0,
      skuIds: new Set(),
      amount: 0,
      amountAvailable: false,
      departments: [],
      departmentByName: new Map(),
    });
  }
  return buckets.get(code);
}

// Build the Departments landing page entirely from state that is already
// loaded by refreshAll(): dashboard.departments is the backend's central
// aggregate and product.fields.amount is the backend-computed authoritative
// amount (CURRENT_COST × SKU QTY, Decimal-safe server-side). This view never
// invents its own price formula. A missing Division mapping is kept visible
// under "ไม่ระบุฝ่าย" rather than silently dropping real rows.
function buildDivisionData(dashboard, departmentDivisions, products) {
  const departments = dashboard?.departments || [];
  const buckets = new Map();

  for (const dept of departments) {
    const info = departmentDivisions?.[dept.name] || null;
    const divisionCode = info?.code || "UNMAPPED";
    const divisionName = info?.name || "ไม่ระบุฝ่าย";
    const bucket = bucketFor(buckets, divisionCode, divisionName);
    const item = {
      name: dept.name,
      skuCount: dept.skuCount || 0,
      rowCount: dept.rowCount || 0,
      reviewCount: dept.reviewCount || 0,
      weight: dept.totals?.weight_qty || 0,
      puQty: dept.totals?.pu_qty || 0,
      skuQty: dept.totals?.sku_qty || 0,
      amount: 0,
      amountAvailable: false,
    };
    bucket.departments.push(item);
    bucket.departmentByName.set(dept.name, item);
    bucket.departmentCount += 1;
    bucket.rowCount += item.rowCount;
    bucket.reviewCount += item.reviewCount;
    bucket.fallbackSkuCount += item.skuCount;
  }

  for (const product of products || []) {
    if (product.suspectedNonProduct) continue;
    const info = departmentDivisions?.[product.department] || null;
    const divisionCode = info?.code || "UNMAPPED";
    const divisionName = info?.name || "ไม่ระบุฝ่าย";
    const bucket = bucketFor(buckets, divisionCode, divisionName);

    const identity = identityForProduct(product);
    if (identity) bucket.skuIds.add(String(identity));

    const amount = product.fields?.amount?.value;
    if (typeof amount === "number" && Number.isFinite(amount)) {
      bucket.amount += amount;
      bucket.amountAvailable = true;
      const dept = bucket.departmentByName.get(product.department);
      if (dept) {
        dept.amount += amount;
        dept.amountAvailable = true;
      }
    }
  }

  return [...buckets.values()]
    .map((bucket) => ({
      divisionCode: bucket.divisionCode,
      divisionName: bucket.divisionName,
      departmentCount: bucket.departmentCount,
      rowCount: bucket.rowCount,
      reviewCount: bucket.reviewCount,
      skuCount: bucket.skuIds.size || bucket.fallbackSkuCount,
      amount: Math.round((bucket.amount + Number.EPSILON) * 100) / 100,
      amountAvailable: bucket.amountAvailable,
      departments: [...bucket.departments].sort((a, b) => a.name.localeCompare(b.name, "th")),
    }))
    .filter((division) => division.departmentCount > 0)
    .sort((a, b) => {
      if (a.divisionCode === "UNMAPPED") return 1;
      if (b.divisionCode === "UNMAPPED") return -1;
      return a.divisionCode.localeCompare(b.divisionCode);
    });
}

function divisionCard(division, store) {
  const card = document.createElement("div");
  card.className = "division-card";
  card.style.setProperty("--division-color", colorForDivision(division.divisionName));
  card.setAttribute("role", "button");
  card.tabIndex = 0;

  const hero = division.amountAvailable ? fmtBaht(division.amount) : `${fmtNum(division.skuCount)} SKU`;
  const heroLabel = division.amountAvailable ? "มูลค่ารวม" : "จำนวน SKU";
  card.innerHTML = `
    <div class="division-card-head">
      <span class="division-card-name"><span class="division-card-dot"></span>${escapeHtml(division.divisionName)}</span>
      <span class="division-card-arrow" aria-hidden="true">›</span>
    </div>
    <div class="division-card-meta">${fmtNum(division.departmentCount)} แผนก</div>
    <div class="division-card-value mono">${hero}</div>
    <div class="division-card-value-label">${heroLabel}</div>
    <div class="division-card-foot">
      <span>${fmtNum(division.skuCount)} SKU · ${fmtNum(division.rowCount)} รายการ</span>
      ${division.reviewCount > 0 ? `<span class="dept-card-badge warn">${fmtNum(division.reviewCount)} ต้องตรวจสอบ</span>` : ""}
    </div>
  `;

  const open = () => {
    store.navigate("divisionDetail", {
      divisionDetail: {
        source: "departments",
        divisionCode: division.divisionCode,
        divisionName: division.divisionName,
        amountAvailable: division.amountAvailable,
        summary: {
          departmentCount: division.departmentCount,
          skuCount: division.skuCount,
          rowCount: division.rowCount,
          reviewCount: division.reviewCount,
          amount: division.amount,
        },
        departments: division.departments,
      },
    });
  };
  card.addEventListener("click", open);
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      open();
    }
  });
  return card;
}

// Departments is deliberately Division-first: the old page put every
// department on one dense screen (plus weight/PU/SKU-qty details), which
// made the hierarchy hard to scan. The landing page now has one simple card
// per real Division; clicking it drills into the existing Division Detail
// view, then a Department click hands off to the one existing Products view.
export function renderDepartments(container, store) {
  const { dashboard, departmentDivisions, products } = store.state;
  const divisions = buildDivisionData(dashboard, departmentDivisions || {}, products || []);
  const totalDepartments = (dashboard?.departments || []).length;

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Departments</div>
      <div class="workspace-sub">${fmtNum(divisions.length)} ฝ่าย · ${fmtNum(totalDepartments)} แผนก</div>
    </div>
    <div class="division-grid" id="divisionGrid"></div>
  `;

  const grid = container.querySelector("#divisionGrid");
  if (!divisions.length) {
    grid.innerHTML = `<div class="empty-state division-grid-empty"><div class="icon">🏷️</div><div class="title">ยังไม่มีข้อมูลแผนก</div><div>เพิ่ม PDF เพื่อเริ่มวิเคราะห์</div></div>`;
    return;
  }

  divisions.forEach((division) => grid.appendChild(divisionCard(division, store)));
}
