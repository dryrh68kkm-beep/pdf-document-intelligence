import { api } from "../api.js";
import { icons } from "../icons.js";
import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";

// Official Master (read-only, ground truth - only a row *count* is exposed
// by the backend via /api/master/snapshot/status, never the full row set)
// vs Local Verified Master (user-confirmed barcodes, persisted in SQLite,
// fully loaded via GET /api/master/local - editable only by adding new
// entries, never overwriting Official). Spec P3 items 18-19. The table on
// this page paginates the already-loaded Local Verified list; the Official
// Master's ~35k rows are surfaced only as the KPI count the backend already
// computes, since there is no per-row Official Master endpoint to page
// through client-side (see final report: intentionally not adding one).

let deptFilter = "";
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("th-TH", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const COLUMNS = [
  { key: "barcode", label: "BARCODE", render: (e) => `<span class="mono">${e.barcode}</span>` },
  { key: "article", label: "ARTICLE", render: (e) => `<span class="mono">${e.article_code || "—"}</span>` },
  { key: "name", label: "ชื่อสินค้า", render: (e) => e.product_name },
  { key: "dept", label: "แผนก", render: (e) => e.department || "—" },
  { key: "unit", label: "PU", render: (e) => e.unit || "—" },
  { key: "updated", label: "อัปเดตล่าสุด", render: (e) => `<span class="mono">${new Date(e.updated_at).toLocaleDateString("th-TH")}</span>` },
  {
    key: "actions",
    label: "จัดการ",
    render: () => `
      <div class="data-table-actions">
        <button type="button" class="icon-btn-sm tone-accent" data-row-action="edit" aria-label="แก้ไข">${icons.edit}</button>
      </div>`,
  },
];

function renderTable(container, entries) {
  const host = container.querySelector("#pmTableHost");
  const paginationHost = container.querySelector("#pmPaginationHost");
  if (!host) return;
  const filtered = deptFilter ? entries.filter((e) => e.department === deptFilter) : entries;
  const { pageRows, total } = paginate(filtered, page, pageSize);
  renderDataTable(host, pageRows, {
    columns: COLUMNS,
    getRowId: (e) => e.id ?? e.barcode,
    emptyMessage: "ยังไม่มีรายการ",
  });
  renderPaginationBar(paginationHost, {
    page,
    pageSize,
    total,
    onPageChange: (p) => { page = p; renderTable(container, entries); },
    onPageSizeChange: (size) => { pageSize = size; page = 1; renderTable(container, entries); },
  });
}

function renderImportControl(container, store) {
  container.innerHTML = `
    <input type="file" id="pmImportFile" accept=".csv" hidden />
    <button class="btn btn-primary" id="pmImportBtn" type="button">
      <span class="nav-icon" aria-hidden="true">${icons.upload}</span> Import Master Catalog (CSV)
    </button>
    <span class="dp-save-feedback" id="pmImportFeedback"></span>
  `;
  const fileInput = container.querySelector("#pmImportFile");
  const importBtn = container.querySelector("#pmImportBtn");
  const feedback = container.querySelector("#pmImportFeedback");

  importBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    fileInput.value = "";
    if (!file) return;
    importBtn.disabled = true;
    feedback.textContent = "กำลังนำเข้า...";
    feedback.className = "dp-save-feedback";
    try {
      await api.importMasterCatalog(file);
      feedback.textContent = "✓ นำเข้าสำเร็จ";
      feedback.className = "dp-save-feedback ok";
      await renderProductMaster(document.getElementById("workspace"), store);
    } catch (err) {
      feedback.textContent = `นำเข้าไม่สำเร็จ: ${String(err.message || err)}`;
      feedback.className = "dp-save-feedback error";
      importBtn.disabled = false;
    }
  });
}

function kpiIconCard(value, label, icon, tone) {
  return `
    <div class="kpi-icon-card">
      <div class="kpi-icon-badge tone-${tone}">${icon}</div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-label">${label}</div>
    </div>`;
}

export async function renderProductMaster(container, store) {
  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Product Master</div>
      <div class="workspace-sub">จัดการข้อมูลสินค้าอ้างอิง (Master Data)</div>
    </div>
    <div class="empty-state" style="padding:50px 20px;">
      <div class="icon">🗂️</div>
      <div class="title">กำลังโหลดข้อมูล Product Master</div>
    </div>
  `;

  const [snapshotStatus, localMaster] = await Promise.all([
    api.masterSnapshotStatus(),
    api.listLocalMaster(),
  ]);

  // (a) No snapshot at all - explain and offer a real working import flow.
  if (!snapshotStatus.exists) {
    container.innerHTML = `
      <div class="workspace-header">
        <div class="workspace-title">Product Master</div>
        <div class="workspace-sub">จัดการข้อมูลสินค้าอ้างอิง (Master Data) · Local Verified ${localMaster.count.toLocaleString("th-TH")} รายการ</div>
      </div>
      <div class="empty-state" style="padding:60px 20px;">
        <div class="icon">🗂️</div>
        <div class="title">ยังไม่มีฐานข้อมูลสินค้ากลาง (Official Master)</div>
        <div>นำเข้าไฟล์ CSV เพื่อเริ่มใช้งานการจับคู่ Barcode/ชื่อสินค้าอัตโนมัติ</div>
        <div id="pmImportHost" style="margin-top:16px;"></div>
      </div>
    `;
    renderImportControl(container.querySelector("#pmImportHost"), store);
    return;
  }

  // (b) Snapshot exists but is empty.
  if (snapshotStatus.productCount === 0) {
    container.innerHTML = `
      <div class="workspace-header">
        <div class="workspace-title">Product Master</div>
        <div class="workspace-sub">นำเข้าล่าสุด ${fmtDate(snapshotStatus.lastUpdated)} · Local Verified ${localMaster.count.toLocaleString("th-TH")} รายการ</div>
      </div>
      <div class="empty-state" style="padding:60px 20px;">
        <div class="icon">⚠️</div>
        <div class="title">นำเข้าฐานข้อมูลแล้วแต่ไม่พบรายการสินค้า</div>
        <div>ตรวจสอบว่าไฟล์ CSV มีคอลัมน์ BARCODE / ART_SV_NAME ที่ถูกต้อง แล้วลองนำเข้าใหม่</div>
        <div id="pmImportHost" style="margin-top:16px;"></div>
      </div>
    `;
    renderImportControl(container.querySelector("#pmImportHost"), store);
    return;
  }

  // (c) Snapshot exists with data.
  const departments = [...new Set(localMaster.entries.map((e) => e.department).filter(Boolean))].sort();

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Product Master</div>
      <div class="workspace-sub">จัดการข้อมูลสินค้าอ้างอิง (Master Data)</div>
    </div>
    <div class="kpi-icon-row">
      ${kpiIconCard(snapshotStatus.productCount.toLocaleString("th-TH"), "สินค้าทั้งหมด (Official Master)", icons.box, "accent")}
      ${kpiIconCard(localMaster.count.toLocaleString("th-TH"), "Local Verified", icons.checkCircle, "success")}
      ${kpiIconCard(departments.length.toLocaleString("th-TH"), "แผนก", icons.building, "purple")}
      ${kpiIconCard(fmtDate(snapshotStatus.lastUpdated), "อัปเดตล่าสุด (Official)", icons.trendingUp, "neutral")}
    </div>
    <div id="pmImportHost" style="margin-bottom:16px;"></div>
    <div class="filter-chip-bar">
      <input id="pmSearch" class="search-input" type="text" placeholder="ค้นหา Barcode / Article / ชื่อสินค้า..." autocomplete="off" />
      <select id="pmDeptSelect" class="filter-chip">
        <option value=""${!deptFilter ? " selected" : ""}>ทุกแผนก</option>
        ${departments.map((d) => `<option value="${d}"${deptFilter === d ? " selected" : ""}>${d}</option>`).join("")}
      </select>
    </div>
    <div class="workspace-sub" style="margin-bottom:8px;">Local Verified Master — สินค้าที่ผู้ใช้ยืนยันเองจาก Review (บันทึกถาวร ใช้แก้ปัญหา Unknown Barcode ในเอกสารถัดไปโดยอัตโนมัติ)</div>
    ${localMaster.count === 0
      ? `<div class="empty-state" style="padding:40px 20px;"><div class="icon">📋</div><div class="title">ยังไม่มีรายการ Local Master</div><div>รายการจะถูกเพิ่มโดยอัตโนมัติเมื่อยืนยัน Barcode ที่ไม่พบใน Official Master จากหน้า Review</div></div>`
      : `<div id="pmTableHost"></div><div id="pmPaginationHost"></div>`}
  `;

  renderImportControl(container.querySelector("#pmImportHost"), store);

  if (localMaster.count > 0) {
    renderTable(container, localMaster.entries);

    container.querySelector("#pmDeptSelect").addEventListener("change", (e) => {
      deptFilter = e.target.value;
      page = 1;
      renderTable(container, localMaster.entries);
    });

    let debounce = null;
    container.querySelector("#pmSearch").addEventListener("input", (e) => {
      clearTimeout(debounce);
      const val = e.target.value;
      debounce = setTimeout(async () => {
        const res = await api.listLocalMaster(val);
        page = 1;
        renderTable(container, res.entries);
      }, 200);
    });
  }
}
