import { api } from "../api.js";
import { icons } from "../icons.js";
import { renderDataTable } from "../components/dataTable.js";
import { paginate, renderPaginationBar, PAGE_SIZE_OPTIONS } from "../components/pagination.js";
import { escapeHtml } from "../escape.js";

// Official Master (read-only, ground truth - only a row *count* is exposed
// by the backend via /api/master/snapshot/status, never the full row set)
// vs Local Verified Master (user-confirmed barcodes, persisted in SQLite,
// fully loaded via GET /api/master/local - editable only by adding new
// entries, never overwriting Official). Spec P3 items 18-19. The table on
// this page paginates the already-loaded Local Verified list; the Official
// Master's ~50k rows are surfaced as the KPI count plus a single-barcode
// lookup (GET /api/master/official/lookup) so a user can confirm a specific
// product really imported - there is still no per-row listing/browsing
// endpoint for the full Official Master (intentionally not adding one).

let deptFilter = "";
let page = 1;
let pageSize = PAGE_SIZE_OPTIONS[0];

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("th-TH", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

const COLUMNS = [
  { key: "barcode", label: "BARCODE", render: (e) => `<span class="mono">${escapeHtml(e.barcode)}</span>` },
  { key: "article", label: "ARTICLE", render: (e) => `<span class="mono">${escapeHtml(e.article_code) || "—"}</span>` },
  { key: "name", label: "ชื่อสินค้า", render: (e) => escapeHtml(e.product_name) },
  { key: "dept", label: "แผนก", render: (e) => escapeHtml(e.department) || "—" },
  { key: "unit", label: "PU", render: (e) => escapeHtml(e.unit) || "—" },
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

function renderImportControl(container, store, isStale) {
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
      // The upload can take a moment - if the user has since navigated
      // away, main.js's render() has already moved on to a newer
      // generation and rewritten #workspace for a different view. Without
      // this check the recursive renderProductMaster() below would
      // overwrite that other view's DOM out from under it.
      if (isStale && isStale()) return;
      feedback.textContent = "✓ นำเข้าสำเร็จ";
      feedback.className = "dp-save-feedback ok";
      await renderProductMaster(document.getElementById("workspace"), store, isStale);
    } catch (err) {
      if (isStale && isStale()) return;
      feedback.textContent = `นำเข้าไม่สำเร็จ: ${String(err.message || err)}`;
      feedback.className = "dp-save-feedback error";
      importBtn.disabled = false;
    }
  });
}

function renderLookupControl(container) {
  container.innerHTML = `
    <div class="workspace-sub" style="margin-bottom:6px;">ตรวจสอบ Barcode ใน Official Master — ยืนยันว่าไฟล์ที่นำเข้ามีสินค้านี้จริงหรือไม่</div>
    <div class="filter-chip-bar">
      <input id="pmOfficialLookup" class="search-input" type="text" placeholder="พิมพ์ Barcode เพื่อตรวจสอบใน Official Master..." autocomplete="off" />
    </div>
    <div id="pmOfficialLookupResult" class="dp-save-feedback"></div>
  `;
  const input = container.querySelector("#pmOfficialLookup");
  const result = container.querySelector("#pmOfficialLookupResult");
  let debounce = null;
  // Race guard: clearTimeout only cancels a still-*pending* timer, not a
  // fetch already in flight. Typing a second barcode while the first
  // lookup's request is still on the wire starts a second fetch that can
  // resolve out of order - a slow response for an earlier barcode landing
  // after a faster response for the current one would silently overwrite
  // the correct, currently-displayed result with a stale one. requestId
  // makes each keystroke's callback check it's still the latest before
  // touching the DOM.
  let requestId = 0;
  input.addEventListener("input", (e) => {
    clearTimeout(debounce);
    const barcode = e.target.value.trim();
    const myRequestId = ++requestId;
    if (!barcode) {
      result.textContent = "";
      result.className = "dp-save-feedback";
      return;
    }
    debounce = setTimeout(async () => {
      result.textContent = "กำลังตรวจสอบ...";
      result.className = "dp-save-feedback";
      try {
        const res = await api.officialMasterLookup(barcode);
        if (myRequestId !== requestId) return;
        if (res.found) {
          result.textContent = `✓ พบใน Official Master: ${res.name}${res.articleCode ? ` (Article: ${res.articleCode})` : ""}`;
          result.className = "dp-save-feedback ok";
        } else {
          result.textContent = `✗ ไม่พบ Barcode "${barcode}" ใน Official Master`;
          result.className = "dp-save-feedback error";
        }
      } catch (err) {
        if (myRequestId !== requestId) return;
        result.textContent = `ตรวจสอบไม่สำเร็จ: ${String(err.message || err)}`;
        result.className = "dp-save-feedback error";
      }
    }, 300);
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

export async function renderProductMaster(container, store, isStale) {
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
  // This is the one view whose own render function does real async work
  // (everything else's data is already loaded by the time main.js calls
  // it) - a background poll firing while this fetch is still in flight
  // starts a second, overlapping call to this same function, and the
  // user navigating away entirely means a *different* view now owns
  // #workspace. Either way, this call's own await just resolved into a
  // world where it's no longer the current render - bail out before
  // writing DOM instead of overwriting whatever's actually on screen now.
  if (isStale && isStale()) return;

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
    renderImportControl(container.querySelector("#pmImportHost"), store, isStale);
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
    renderImportControl(container.querySelector("#pmImportHost"), store, isStale);
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
    <div id="pmOfficialLookupHost" style="margin-bottom:16px;"></div>
    <div class="filter-chip-bar">
      <input id="pmSearch" class="search-input" type="text" placeholder="ค้นหา Barcode / Article / ชื่อสินค้า... (เฉพาะ Local Verified)" autocomplete="off" />
      <select id="pmDeptSelect" class="filter-chip">
        <option value=""${!deptFilter ? " selected" : ""}>ทุกแผนก</option>
        ${departments.map((d) => `<option value="${escapeHtml(d)}"${deptFilter === d ? " selected" : ""}>${escapeHtml(d)}</option>`).join("")}
      </select>
    </div>
    <div class="workspace-sub" style="margin-bottom:8px;">Local Verified Master — สินค้าที่ผู้ใช้ยืนยันเองจาก Review (บันทึกถาวร ใช้แก้ปัญหา Unknown Barcode ในเอกสารถัดไปโดยอัตโนมัติ)</div>
    ${localMaster.count === 0
      ? `<div class="empty-state" style="padding:40px 20px;"><div class="icon">📋</div><div class="title">ยังไม่มีรายการ Local Master</div><div>รายการจะถูกเพิ่มโดยอัตโนมัติเมื่อยืนยัน Barcode ที่ไม่พบใน Official Master จากหน้า Review</div></div>`
      : `<div id="pmTableHost"></div><div id="pmPaginationHost"></div>`}
  `;

  renderImportControl(container.querySelector("#pmImportHost"), store, isStale);
  renderLookupControl(container.querySelector("#pmOfficialLookupHost"));

  if (localMaster.count > 0) {
    renderTable(container, localMaster.entries);

    container.querySelector("#pmDeptSelect").addEventListener("change", (e) => {
      deptFilter = e.target.value;
      page = 1;
      renderTable(container, localMaster.entries);
    });

    let debounce = null;
    let searchRequestId = 0;
    container.querySelector("#pmSearch").addEventListener("input", (e) => {
      clearTimeout(debounce);
      const val = e.target.value;
      const myRequestId = ++searchRequestId;
      debounce = setTimeout(async () => {
        const res = await api.listLocalMaster(val);
        // A slower, earlier keystroke's response landing after a faster,
        // later one would otherwise repaint the table with stale results.
        if (myRequestId !== searchRequestId) return;
        page = 1;
        renderTable(container, res.entries);
      }, 200);
    });
  }
}
