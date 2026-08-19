import { api } from "../api.js";

// Official Master (34,927+ rows, read-only, ground truth) vs Local
// Verified Master (user-confirmed barcodes, persisted in SQLite, editable
// only by adding new entries - never overwriting Official). Spec P3
// items 18-19.
export async function renderProductMaster(container, store) {
  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Product Master</div>
      <div class="workspace-sub">กำลังโหลด...</div>
    </div>
  `;

  const [officialCount, localMaster] = await Promise.all([
    api.officialMasterCount(),
    api.listLocalMaster(),
  ]);

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Product Master</div>
      <div class="workspace-sub">Official Master ${officialCount.count.toLocaleString("th-TH")} รายการ (read-only) · Local Verified ${localMaster.count.toLocaleString("th-TH")} รายการ</div>
    </div>
    <div class="search-wrap" style="max-width:360px;margin-bottom:14px;">
      <input id="pmSearch" type="text" placeholder="ค้นหา Barcode / Article / ชื่อสินค้า..." autocomplete="off" style="width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--text);" />
    </div>
    <div class="workspace-sub" style="margin-bottom:8px;">Local Verified Master — สินค้าที่ผู้ใช้ยืนยันเองจาก Review (บันทึกถาวร ใช้แก้ปัญหา Unknown Barcode ในเอกสารถัดไปโดยอัตโนมัติ)</div>
    <table class="pm-table">
      <thead><tr><th>Barcode</th><th>Article</th><th>ชื่อสินค้า</th><th>แผนก</th><th>หน่วย</th><th>อัปเดตล่าสุด</th></tr></thead>
      <tbody id="pmBody"></tbody>
    </table>
  `;

  function renderRows(entries) {
    const body = container.querySelector("#pmBody");
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
  renderRows(localMaster.entries);

  let debounce = null;
  container.querySelector("#pmSearch").addEventListener("input", (e) => {
    clearTimeout(debounce);
    const val = e.target.value;
    debounce = setTimeout(async () => {
      const res = await api.listLocalMaster(val);
      renderRows(res.entries);
    }, 200);
  });
}
