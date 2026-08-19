import { api } from "../api.js";

const FLAG_LABEL = {
  TEXT_LAYER_UNRELIABLE: "PDF ต้นฉบับ: font ที่ฝังมาไม่มี glyph ของสระบน/ล่างและวรรณยุกต์ไทย — ใช้ OCR อ่านจากภาพแทน",
  OCR_LOW_CONFIDENCE: "OCR อ่านได้แต่ความมั่นใจต่ำกว่าเกณฑ์ จึงคงค่าดิบจาก PDF ไว้แทนการเดา",
  SOURCE_CONFLICT: "ข้อความจาก PDF และจาก OCR ไม่ตรงกัน ควรเทียบกับต้นฉบับก่อนยืนยัน",
  MISSING_FIELD: "ไม่พบค่าในตำแหน่งนี้",
  TYPE_PARSE_FAILED: "แปลงชนิดข้อมูลไม่สำเร็จ",
  CATALOG_MATCH: "พบ Barcode นี้ในฐานข้อมูลสินค้ากลาง — ใช้ชื่อจากฐานข้อมูลแทนการอ่านจาก PDF/OCR",
  LOCAL_MASTER_MATCH: "พบ Barcode นี้ใน Local Product Master ที่ผู้ใช้ยืนยันเอง",
  AMOUNT_MISMATCH: "จำนวน x ราคาต่อหน่วย ไม่ตรงกับยอดเงินที่บันทึกไว้",
  MISSING_DEPARTMENT: "ยังไม่ระบุแผนก",
};
const SOURCE_LABEL = {
  pdf_text: "PDF text layer", ocr: "OCR (Tesseract tha+eng)", cross_validated: "PDF + OCR ตรงกัน",
  master_catalog: "ฐานข้อมูลสินค้ากลาง (ยืนยันแล้ว)",
};
const FIELD_LABEL = {
  dn_no: "DN no", do_no: "DO", order_no: "Order no.", line: "Line", pallet: "Pallet", lot: "Lot",
  article: "Article", barcode: "Barcode", name: "ชื่อสินค้า", weight_qty: "น้ำหนัก", pu_qty: "PU qty",
  sku_qty: "SKU qty", remarks: "หมายเหตุ", department: "แผนก", unit_price: "ราคาต่อหน่วย", amount: "ยอดเงิน",
  unit: "หน่วย",
};
const EDITABLE_FIELDS = new Set(["name", "weight_qty", "pu_qty", "sku_qty", "unit", "unit_price", "amount", "department"]);
const IDENTIFIER_FIELDS = new Set(["barcode", "article"]);
const REASON_PRESETS = ["OCR อ่านผิด", "ข้อมูล PDF ผิด", "ยืนยันจากเอกสารต้นฉบับ", "ยืนยันจาก Product Master", "อื่น ๆ"];

// Per-panel edit session state (module-level: one detail panel open at a time).
let editing = false;
let pendingEdits = {}; // fieldName -> new raw string value
let pendingReason = "";
let currentProduct = null;
let onDirtyChange = () => {};

function isDirty() {
  return editing && Object.keys(pendingEdits).length > 0;
}

function fieldBlock(name, fv, editable) {
  if (!fv) return "";
  const isThai = /[฀-๛]/.test(String(fv.value || fv.raw || ""));
  const sourceNote = name === "name" ? `<div class="dp-source-note">ที่มา: ${SOURCE_LABEL[fv.source] || fv.source}</div>` : "";
  const inEdit = editing && editable;

  let valueHtml;
  if (inEdit) {
    const val = pendingEdits[name] !== undefined ? pendingEdits[name] : (fv.value ?? "");
    valueHtml = `<input class="dp-edit-input" data-field="${name}" type="text" value="${String(val).replace(/"/g, "&quot;")}" />`;
  } else {
    valueHtml = `<div class="dp-value${isThai ? " thai" : ""}">${fv.value ?? "—"}${fv.corrected ? ' <span class="dp-corrected-badge">แก้ไขแล้ว</span>' : ""}</div>`;
  }

  let html = `
    <div class="dp-field">
      <div class="dp-label">${FIELD_LABEL[name] || name}${inEdit ? "" : ""}</div>
      ${valueHtml}
      ${sourceNote}
    </div>`;
  if (fv.review || fv.source === "master_catalog" || fv.corrected) {
    html += `
      <div class="dp-field">
        <div class="dp-label">หลักฐาน${fv.review ? "" : " (ยืนยันแล้ว ไม่ต้องตรวจสอบ)"}</div>
        <div class="dp-value${isThai ? " thai" : ""}" style="margin-bottom:4px;">Raw PDF: ${fv.raw || "—"}</div>
        ${fv.ocrRaw ? `<div class="dp-value thai" style="margin-bottom:4px;">OCR: ${fv.ocrRaw} (${Math.round((fv.ocrConfidence || 0) * 100)}%)</div>` : ""}
        <ul class="dp-reasons">${(fv.flags || []).map((f) => `<li>${FLAG_LABEL[f] || f}</li>`).join("")}</ul>
      </div>`;
  }
  return html;
}

function editFieldBlock(name, fv) {
  return fieldBlock(name, fv, EDITABLE_FIELDS.has(name) || IDENTIFIER_FIELDS.has(name));
}

function renderHistory(container, rowId) {
  container.innerHTML = `<div class="dp-history-loading">กำลังโหลดประวัติ...</div>`;
  api.productHistory(rowId).then((history) => {
    if (!history.length) {
      container.innerHTML = `<div class="workspace-sub">ยังไม่มีการแก้ไข</div>`;
      return;
    }
    container.innerHTML = history
      .map((h) => {
        const time = new Date(h.createdAt).toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" });
        const label = FIELD_LABEL[h.field] || h.field;
        const isUndo = h.field !== undefined && h.reason === "undo";
        return `
          <div class="dp-audit-entry">
            <div class="dp-audit-time">${time}</div>
            <div class="dp-audit-change"><b>${label}</b>: ${h.oldValue ?? "—"} → ${h.newValue ?? "—"}${isUndo ? " (ย้อนกลับ)" : ""}</div>
            ${h.reason && h.reason !== "undo" ? `<div class="dp-audit-reason">เหตุผล: ${h.reason}</div>` : ""}
            ${!isUndo ? `<button class="dp-undo-btn" data-correction-id="${h.id}">ย้อนกลับ</button>` : ""}
          </div>`;
      })
      .join("");
    container.querySelectorAll(".dp-undo-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await api.undoCorrection(rowId, btn.dataset.correctionId);
          document.dispatchEvent(new CustomEvent("product-saved", { detail: { rowId } }));
        } catch {
          btn.disabled = false;
        }
      });
    });
  });
}

export function renderProductDetail(container, product, store) {
  currentProduct = product;
  const f = product.fields;

  container.innerHTML = `
    <div class="side-panel-head">
      <div>
        <div class="side-panel-title">รายละเอียดสินค้า</div>
        <div class="workspace-sub">${product.department} · ${product.docFilename} · หน้า ${product.page}</div>
      </div>
      <button class="close" id="dpClose" aria-label="ปิด" type="button">✕</button>
    </div>
    ${product.suspectedNonProduct ? `<div class="dp-badge">🎁 สงสัยว่าไม่ใช่สินค้า: ${(product.nonProductReasons || []).join(", ")}</div>` : ""}
    <div class="dp-edit-toolbar">
      ${editing ? "" : `<button class="btn" id="dpEditToggle" type="button">แก้ไข</button>`}
      ${editing ? `<span class="dp-editing-badge">โหมดแก้ไข</span>` : ""}
    </div>
    <div class="dp-row">
      ${editFieldBlock("barcode", f.barcode)}
      ${editFieldBlock("article", f.article)}
    </div>
    ${editFieldBlock("department", { value: product.department, source: "pdf_text" })}
    ${editFieldBlock("name", f.name)}
    <div class="dp-row">
      ${editFieldBlock("weight_qty", f.weight_qty)}
      ${editFieldBlock("pu_qty", f.pu_qty)}
      ${editFieldBlock("sku_qty", f.sku_qty)}
    </div>
    <div class="dp-row">
      ${fieldBlock("dn_no", f.dn_no, false)}
      ${fieldBlock("do_no", f.do_no, false)}
      ${fieldBlock("order_no", f.order_no, false)}
    </div>
    ${editing ? `
      <div class="dp-field">
        <div class="dp-label">เหตุผลการแก้ไข${IDENTIFIER_FIELDS.has("barcode") ? " (บังคับถ้าแก้ Barcode/Article)" : ""}</div>
        <select class="dp-reason-select" id="dpReasonSelect">
          <option value="">— เลือกเหตุผล —</option>
          ${REASON_PRESETS.map((r) => `<option value="${r}" ${pendingReason === r ? "selected" : ""}>${r}</option>`).join("")}
        </select>
        <textarea class="dp-reason-text" id="dpReasonText" placeholder="รายละเอียดเพิ่มเติม (ถ้ามี)">${pendingReason && !REASON_PRESETS.includes(pendingReason) ? pendingReason : ""}</textarea>
      </div>
      <div class="dp-save-bar">
        <button class="btn" id="dpCancelEdit" type="button">ยกเลิก</button>
        <button class="btn btn-primary" id="dpSaveEdit" type="button">บันทึกการแก้ไข</button>
        <span class="dp-save-feedback" id="dpSaveFeedback"></span>
      </div>
    ` : ""}
    <div class="dp-source-link" id="dpShowPdf">👁 ดูจากเอกสารต้นฉบับ (หน้า ${product.page})</div>
    <div id="dpPdfWrap"></div>
    <div class="dp-history-section">
      <div class="dp-label" style="margin-top:16px;">ประวัติการแก้ไข</div>
      <div id="dpHistory"></div>
    </div>
  `;

  renderHistory(container.querySelector("#dpHistory"), product.rowId);

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

  const editToggle = container.querySelector("#dpEditToggle");
  if (editToggle) {
    editToggle.addEventListener("click", () => {
      editing = true;
      pendingEdits = {};
      pendingReason = "";
      renderProductDetail(container, currentProduct, store);
    });
  }

  container.querySelectorAll(".dp-edit-input").forEach((input) => {
    input.addEventListener("input", () => {
      pendingEdits[input.dataset.field] = input.value;
      onDirtyChange(isDirty());
    });
  });

  const cancelBtn = container.querySelector("#dpCancelEdit");
  if (cancelBtn) {
    cancelBtn.addEventListener("click", () => {
      editing = false;
      pendingEdits = {};
      pendingReason = "";
      onDirtyChange(false);
      renderProductDetail(container, currentProduct, store);
    });
  }

  const reasonSelect = container.querySelector("#dpReasonSelect");
  const reasonText = container.querySelector("#dpReasonText");
  if (reasonSelect) reasonSelect.addEventListener("change", () => { pendingReason = reasonSelect.value || reasonText.value; });
  if (reasonText) reasonText.addEventListener("input", () => { pendingReason = reasonText.value || reasonSelect.value; });

  const saveBtn = container.querySelector("#dpSaveEdit");
  if (saveBtn) {
    saveBtn.addEventListener("click", async () => {
      const feedback = container.querySelector("#dpSaveFeedback");
      const identifierChanged = Object.keys(pendingEdits).some((f) => IDENTIFIER_FIELDS.has(f));
      if (identifierChanged && !pendingReason.trim()) {
        feedback.textContent = "ต้องระบุเหตุผลเมื่อแก้ Barcode/Article";
        feedback.className = "dp-save-feedback error";
        return;
      }
      saveBtn.disabled = true;
      feedback.textContent = "กำลังบันทึก...";
      feedback.className = "dp-save-feedback";
      try {
        for (const [field, rawValue] of Object.entries(pendingEdits)) {
          const numeric = ["weight_qty", "pu_qty", "sku_qty", "unit_price", "amount"].includes(field);
          const value = numeric ? (rawValue === "" ? null : Number(rawValue)) : rawValue;
          await api.patchProduct(product.rowId, field, value, pendingReason || null);
        }
        feedback.textContent = "✓ บันทึกแล้ว";
        feedback.className = "dp-save-feedback ok";
        editing = false;
        pendingEdits = {};
        pendingReason = "";
        onDirtyChange(false);
        document.dispatchEvent(new CustomEvent("product-saved", { detail: { rowId: product.rowId } }));
      } catch (err) {
        feedback.textContent = "บันทึกไม่สำเร็จ — ไม่มีการเปลี่ยนแปลงถูกบันทึก";
        feedback.className = "dp-save-feedback error";
        saveBtn.disabled = false;
      }
    });
  }

  return container.querySelector("#dpClose");
}

export function detailPanelIsDirty() {
  return isDirty();
}

export function detailPanelReset() {
  editing = false;
  pendingEdits = {};
  pendingReason = "";
}

export function setDirtyChangeListener(fn) {
  onDirtyChange = fn;
}
