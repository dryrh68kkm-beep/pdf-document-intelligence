import { api } from "../api.js";
import { icons } from "../icons.js";

// Official Master (34,927+ rows, read-only, ground truth) vs Local
// Verified Master (user-confirmed barcodes, persisted in SQLite, editable
// only by adding new entries - never overwriting Official). Spec P3
// items 18-19. Phase 6 adds a real in-web CSV import flow driven by
// GET /api/master/snapshot/status + POST /api/master/import.

function fmtDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("th-TH", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function renderRows(container, entries) {
  const body = container.querySelector("#pmBody");
  if (!body) return;
  if (!entries.length) {
    body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-faint);padding:20px;">ยังไม่มีรายการ</td></tr>`;
    return;
  }
  body.innerHTML = entries
    .map(
      (e) => `<tr>
        <td class="mono">${e.barcode}</td>
        <td class="mono">${e.article_code || "—"}</td>
        <td>${e.product_name}</td>
        <td>${e.department || "—"}</td>
        <td>${e.unit || "—"}</td>
        <td class="mono">${new Date(e.updated_at).toLocaleDateString("th-TH")}</td>
      </tr>`
    )
    .join("");
}

function renderImportControl(container, store, status) {
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

export async function renderProductMaster(container, store) {
  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Product Master</div>
      <div class="workspace-sub">กำลังตรวจสอบสถานะฐานข้อมูลสินค้ากลาง...</div>
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
        <div class="workspace-sub">Local Verified ${localMaster.count.toLocaleString("th-TH")} รายการ</div>
      </div>
      <div class="empty-state" style="padding:60px 20px;">
        <div class="icon">🗂️</div>
        <div class="title">ยังไม่มีฐานข้อมูลสินค้ากลาง (Official Master)</div>
        <div>นำเข้าไฟล์ CSV เพื่อเริ่มใช้งานการจับคู่ Barcode/ชื่อสินค้าอัตโนมัติ</div>
        <div id="pmImportHost" style="margin-top:16px;"></div>
      </div>
    `;
    renderImportControl(container.querySelector("#pmImportHost"), store, snapshotStatus);
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
    renderImportControl(container.querySelector("#pmImportHost"), store, snapshotStatus);
    return;
  }

  // (c) Snapshot exists with data.
  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Product Master</div>
      <div class="workspace-sub">Official Master ${snapshotStatus.productCount.toLocaleString("th-TH")} รายการ (read-only) · อัปเดตล่าสุด ${fmtDate(snapshotStatus.lastUpdated)} · Local Verified ${localMaster.count.toLocaleString("th-TH")} รายการ</div>
    </div>
    <div id="pmImportHost" style="margin-bottom:16px;"></div>
    <div class="search-wrap" style="max-width:360px;margin-bottom:14px;">
      <input id="pmSearch" type="text" placeholder="ค้นหา Barcode / Article / ชื่อสินค้า..." autocomplete="off" style="width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);" />
    </div>
    <div class="workspace-sub" style="margin-bottom:8px;">Local Verified Master — สินค้าที่ผู้ใช้ยืนยันเองจาก Review (บันทึกถาวร ใช้แก้ปัญหา Unknown Barcode ในเอกสารถัดไปโดยอัตโนมัติ)</div>
    ${localMaster.count === 0
      ? `<div class="empty-state" style="padding:40px 20px;"><div class="icon">📋</div><div class="title">ยังไม่มีรายการ Local Master</div><div>รายการจะถูกเพิ่มโดยอัตโนมัติเมื่อยืนยัน Barcode ที่ไม่พบใน Official Master จากหน้า Review</div></div>`
      : `<table class="pm-table">
          <thead><tr><th>Barcode</th><th>Article</th><th>ชื่อสินค้า</th><th>แผนก</th><th>หน่วย</th><th>อัปเดตล่าสุด</th></tr></thead>
          <tbody id="pmBody"></tbody>
        </table>`}
  `;

  renderImportControl(container.querySelector("#pmImportHost"), store, snapshotStatus);

  if (localMaster.count > 0) {
    renderRows(container, localMaster.entries);

    let debounce = null;
    container.querySelector("#pmSearch").addEventListener("input", (e) => {
      clearTimeout(debounce);
      const val = e.target.value;
      debounce = setTimeout(async () => {
        const res = await api.listLocalMaster(val);
        renderRows(container, res.entries);
      }, 200);
    });
  }
}
