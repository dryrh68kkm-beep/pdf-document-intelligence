import { renderProductTable } from "../components/productTable.js";

export function renderReview(container, store) {
  const { products, panel } = store.state;
  const items = products.filter((p) => p.reviewRequired);

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Review</div>
      <div class="workspace-sub">${items.length.toLocaleString()} รายการต้องตรวจสอบ</div>
    </div>
    ${items.length === 0
      ? `<div class="empty-state"><div class="icon">✅</div><div class="title">ไม่มีรายการต้องตรวจสอบ</div></div>`
      : `<div class="workspace-sub" style="margin-bottom:12px;">คลิกรายการเพื่อดูหลักฐาน (PDF ต้นฉบับ / OCR / confidence) — การแก้ไขค่าและบันทึกกลับ (audit trail) ยังไม่เปิดใช้งานในเวอร์ชันนี้ ใช้เพื่อตรวจสอบเทียบต้นฉบับก่อน export</div><div id="tableHost"></div>`}
  `;

  if (items.length) {
    renderProductTable(container.querySelector("#tableHost"), items, {
      selectedRowId: panel?.rowId,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
    });
  }
}
