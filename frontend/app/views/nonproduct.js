import { renderProductTable } from "../components/productTable.js";

const REASON_LABEL = {
  PAQ_INTERNAL_PREFIX: "รหัสสื่อการตลาด/POP ภายใน (PAQ1_/PAQ2_) ไม่ใช่รหัสสินค้าลูกค้า",
};

export function renderNonProduct(container, store) {
  const { products, panel } = store.state;
  const items = products.filter((p) => p.suspectedNonProduct);

  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">ของแถม / ไม่ใช่สินค้า</div>
      <div class="workspace-sub">${items.length.toLocaleString()} รายการ</div>
    </div>
    <div class="workspace-sub" style="margin-bottom:12px;">
      แยกออกจากยอดสินค้าปกติเฉพาะรายการที่มีสัญญาณเฉพาะเจาะจงเท่านั้น (รหัสสื่อการตลาดภายใน หรือคำระบุ "ของแถม" ชัดเจน) —
      ไม่ใช้ keyword กว้างๆ เพื่อเลี่ยงการตีความสินค้าจริงผิดเป็นของแถม ตรวจสอบเหตุผลได้จากรายการด้านล่าง
    </div>
    ${items.length === 0
      ? `<div class="empty-state"><div class="icon">🎁</div><div class="title">ไม่พบรายการของแถม/ไม่ใช่สินค้า</div></div>`
      : `<div id="tableHost"></div>`}
  `;

  if (items.length) {
    renderProductTable(container.querySelector("#tableHost"), items, {
      selectedRowId: panel?.rowId,
      onRowClick: (row) => store.openPanel({ type: "product", rowId: row.rowId, data: row }),
    });
  }
}
