import { api } from "../api.js";

const FLAG_LABEL = {
  TEXT_LAYER_UNRELIABLE: "PDF ต้นฉบับ: font ที่ฝังมาไม่มี glyph ของสระบน/ล่างและวรรณยุกต์ไทย — ใช้ OCR อ่านจากภาพแทน",
  OCR_LOW_CONFIDENCE: "OCR อ่านได้แต่ความมั่นใจต่ำกว่าเกณฑ์ จึงคงค่าดิบจาก PDF ไว้แทนการเดา",
  SOURCE_CONFLICT: "ข้อความจาก PDF และจาก OCR ไม่ตรงกัน ควรเทียบกับต้นฉบับก่อนยืนยัน",
  MISSING_FIELD: "ไม่พบค่าในตำแหน่งนี้",
  TYPE_PARSE_FAILED: "แปลงชนิดข้อมูลไม่สำเร็จ",
};
const SOURCE_LABEL = { pdf_text: "PDF text layer", ocr: "OCR (Tesseract tha+eng)", cross_validated: "PDF + OCR ตรงกัน" };
const FIELD_LABEL = {
  dn_no: "DN no", do_no: "DO", order_no: "Order no.", line: "Line", pallet: "Pallet", lot: "Lot",
  article: "Article", barcode: "Barcode", name: "ชื่อสินค้า", weight_qty: "น้ำหนัก", pu_qty: "PU qty",
  sku_qty: "SKU qty", remarks: "หมายเหตุ",
};

function fieldBlock(name, fv) {
  if (!fv) return "";
  const isThai = /[฀-๛]/.test(String(fv.value || fv.raw || ""));
  let html = `
    <div class="dp-field">
      <div class="dp-label">${FIELD_LABEL[name] || name}</div>
      <div class="dp-value${isThai ? " thai" : ""}">${fv.value ?? "—"}</div>
    </div>`;
  if (fv.review) {
    html += `
      <div class="dp-field">
        <div class="dp-label">หลักฐาน (${SOURCE_LABEL[fv.source] || fv.source})</div>
        <div class="dp-value${isThai ? " thai" : ""}" style="margin-bottom:4px;">Raw PDF: ${fv.raw || "—"}</div>
        ${fv.ocrRaw ? `<div class="dp-value thai" style="margin-bottom:4px;">OCR: ${fv.ocrRaw} (${Math.round((fv.ocrConfidence || 0) * 100)}%)</div>` : ""}
        <ul class="dp-reasons">${(fv.flags || []).map((f) => `<li>${FLAG_LABEL[f] || f}</li>`).join("")}</ul>
      </div>`;
  }
  return html;
}

export function renderProductDetail(container, product) {
  const f = product.fields;
  container.innerHTML = `
    <div class="side-panel-head">
      <div>
        <div class="side-panel-title">รายละเอียดสินค้า</div>
        <div class="workspace-sub">${product.department} · ${product.docFilename} · หน้า ${product.page}</div>
      </div>
      <button class="close" id="dpClose" aria-label="ปิด" type="button">✕</button>
    </div>
    <div class="dp-row">
      ${fieldBlock("barcode", f.barcode)}
      ${fieldBlock("article", f.article)}
    </div>
    ${fieldBlock("name", f.name)}
    <div class="dp-row">
      ${fieldBlock("weight_qty", f.weight_qty)}
      ${fieldBlock("pu_qty", f.pu_qty)}
      ${fieldBlock("sku_qty", f.sku_qty)}
    </div>
    <div class="dp-row">
      ${fieldBlock("dn_no", f.dn_no)}
      ${fieldBlock("do_no", f.do_no)}
      ${fieldBlock("order_no", f.order_no)}
    </div>
    <div class="dp-source-link" id="dpShowPdf">👁 ดูจากเอกสารต้นฉบับ (หน้า ${product.page})</div>
    <div id="dpPdfWrap"></div>
  `;
  container.querySelector("#dpShowPdf").addEventListener("click", () => {
    const wrap = container.querySelector("#dpPdfWrap");
    if (wrap.dataset.loaded) return;
    wrap.dataset.loaded = "1";
    const iframe = document.createElement("iframe");
    iframe.className = "evidence-pdf";
    iframe.title = "เอกสารต้นฉบับ";
    iframe.src = `${api.pdfUrl(product.docId)}#page=${product.page}&view=FitH`;
    wrap.appendChild(iframe);
  });
  return container.querySelector("#dpClose");
}
