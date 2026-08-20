import { renderProductTable } from "../components/productTable.js";

export function renderReview(container, store) {
  const { products, panel } = store.state;
  const items = products.filter((p) => p.reviewRequired);
  // See views/products.js for why this is captured before the rebuild -
  // same virtual-scroll table, same background-poll-resets-scroll bug.
  const scrollTop = container.querySelector(".vtable-body")?.scrollTop || 0;

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Review</div>
      <div class="workspace-sub">${items.length.toLocaleString()} รายการต้องตรวจสอบ</div>
    </div>
    ${items.length === 0
      ? `<div class="empty-state"><div class="icon">✅</div><div class="title">ไม่มีรายการต้องตรวจสอบ</div></div>`
      : `<div class="workspace-sub" style="margin-bottom:12px;">คลิกรายการเพื่อดูหลักฐาน (PDF ต้นฉบับ / OCR / confidence) แล้วกด "แก้ไข" เพื่อบันทึกค่าที่ถูกต้อง — ทุกการแก้ไขมีประวัติ (audit trail) และ Dashboard จะคำนวณใหม่ทันที</div><div id="tableHost"></div>`}
  `;

  if (items.length) {
    renderProductTable(container.querySelector("#tableHost"), items, {
      selectedRowId: panel?.rowId,
      initialScrollTop: scrollTop,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
    });
  }
}
