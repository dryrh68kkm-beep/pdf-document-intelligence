import { api } from "../api.js";
import { escapeHtml } from "../escape.js";

const FLAG_LABEL = {
  TEXT_LAYER_UNRELIABLE: "PDF ต้นฉบับ: font ที่ฝังมาไม่มี glyph ของสระบน/ล่างและวรรณยุกต์ไทย — ใช้ OCR อ่านจากภาพแทน",
  OCR_LOW_CONFIDENCE: "OCR อ่านได้แต่ความมั่นใจต่ำกว่าเกณฑ์ จึงคงค่าดิบจาก PDF ไว้แทนการเดา",
  SOURCE_CONFLICT: "ข้อความจาก PDF และจาก OCR ไม่ตรงกัน ควรเทียบกับต้นฉบับก่อนยืนยัน",
  MISSING_FIELD: "ไม่พบค่าในตำแหน่งนี้",
  TYPE_PARSE_FAILED: "แปลงชนิดข้อมูลไม่สำเร็จ",
  CATALOG_MATCH: "พบ Barcode นี้ในฐานข้อมูลสินค้ากลาง — ใช้ชื่อจากฐานข้อมูลแทนการอ่านจาก PDF/OCR",
  LOCAL_MASTER_MATCH: "พบ Barcode นี้ใน Local Product Master ที่ผู้ใช้ยืนยันเอง",
  CATALOG_CHECKED_NOT_FOUND: "✓ ตรวจสอบกับ Official Master แล้ว — ไม่พบ Barcode นี้ในฐานข้อมูล จึงใช้ชื่อจาก PDF/OCR แทน (ไม่ใช่ยังไม่ตรวจ)",
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
    valueHtml = `<input class="dp-edit-input" data-field="${name}" type="text" value="${escapeHtml(val)}" />`;
  } else {
    valueHtml = `<div class="dp-value${isThai ? " thai" : ""}">${fv.value == null ? "—" : escapeHtml(fv.value)}${fv.corrected ? ' <span class="dp-corrected-badge">แก้ไขแล้ว</span>' : ""}</div>`;
  }

  let html = `
    <div class="dp-field">
      <div class="dp-label">${FIELD_LABEL[name] || name}${inEdit ? "" : ""}</div>
      ${valueHtml}
      ${sourceNote}
    </div>`;
  if (fv.review || fv.source === "master_catalog" || fv.corrected) {
    const mismatch = fv.ocrRaw && fv.raw && fv.ocrRaw !== fv.raw;
    const confidencePct = fv.ocrConfidence != null ? Math.round(fv.ocrConfidence * 100) : (fv.confidence != null ? Math.round(fv.confidence * 100) : null);
    html += `
      <div class="dp-field">
        <div class="dp-label">หลักฐาน${fv.review ? "" : " (ยืนยันแล้ว ไม่ต้องตรวจสอบ)"}</div>
        <div class="dp-evidence-compare">
          <div class="dp-evidence-row dp-evidence-current">
            <span class="dp-evidence-tag">ค่าปัจจุบัน (ใช้จริง)</span>
            <span class="dp-evidence-val${isThai ? " thai" : ""}">${fv.value == null ? "—" : escapeHtml(fv.value)}</span>
            ${confidencePct != null ? `<span class="dp-evidence-conf">${confidencePct}% มั่นใจ</span>` : ""}
          </div>
          ${fv.ocrRaw ? `
          <div class="dp-evidence-row${mismatch ? " dp-evidence-mismatch" : ""}">
            <span class="dp-evidence-tag">OCR อ่านได้</span>
            <span class="dp-evidence-val thai">${escapeHtml(fv.ocrRaw)}</span>
            ${fv.ocrConfidence != null ? `<span class="dp-evidence-conf">${Math.round(fv.ocrConfidence * 100)}%</span>` : ""}
          </div>` : ""}
          <div class="dp-evidence-row">
            <span class="dp-evidence-tag">Raw PDF text</span>
            <span class="dp-evidence-val${isThai ? " thai" : ""}">${escapeHtml(fv.raw) || "—"}</span>
          </div>
        </div>
        <ul class="dp-reasons">${(fv.flags || [])
          .filter((f) => !(f === "CATALOG_CHECKED_NOT_FOUND" && fv.source === "master_catalog"))
          .map((f) => `<li>${FLAG_LABEL[f] || f}</li>`)
          .join("")}</ul>
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
            <div class="dp-audit-change"><b>${escapeHtml(label)}</b>: ${h.oldValue == null ? "—" : escapeHtml(h.oldValue)} → ${h.newValue == null ? "—" : escapeHtml(h.newValue)}${isUndo ? " (ย้อนกลับ)" : ""}</div>
            ${h.reason && h.reason !== "undo" ? `<div class="dp-audit-reason">เหตุผล: ${escapeHtml(h.reason)}</div>` : ""}
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

  // PR14 (auto refresh without state loss): this panel is rebuilt on every
  // store.set() - including a refreshAll() triggered by something with
  // nothing to do with the row being edited, most commonly another LAN
  // user's unrelated upload finishing processing (main.js's poll loop calls
  // refreshAll() the moment any document's status flips out of
  // "processing"). pendingEdits already survives that (it's module-level
  // state, checked before falling back to the server value - see
  // editFieldBlock below), but destroying and recreating the <input> via
  // innerHTML still kicks focus out and drops the cursor position
  // mid-keystroke. Same capture-before/restore-after technique already
  // used by products.js's local filter box and dashboard.js's product
  // search box, applied here per-field via data-field instead of a single
  // fixed id, since any one of several editable inputs (or the reason
  // textarea) could be the one focused.
  const activeEl = container.contains(document.activeElement) ? document.activeElement : null;
  const focusedField = activeEl?.dataset?.field || (activeEl?.id === "dpReasonText" ? "dpReasonText" : null);
  const focusedSelectionStart = focusedField && typeof activeEl.selectionStart === "number" ? activeEl.selectionStart : null;
  const focusedSelectionEnd = focusedField && typeof activeEl.selectionEnd === "number" ? activeEl.selectionEnd : null;

  container.innerHTML = `
    <div class="side-panel-head">
      <div>
        <div class="side-panel-title">รายละเอียดสินค้า</div>
        <div class="workspace-sub">${escapeHtml(product.department)} · ${escapeHtml(product.docFilename)} · หน้า ${product.page}</div>
      </div>
      <button class="close" id="dpClose" aria-label="ปิด" type="button">✕</button>
    </div>
    ${product.suspectedNonProduct ? `<div class="dp-badge">🎁 สงสัยว่าไม่ใช่สินค้า: ${escapeHtml((product.nonProductReasons || []).join(", "))}</div>` : ""}
    <div class="dp-edit-toolbar">
      ${editing ? "" : `<button class="btn" id="dpEditToggle" type="button">แก้ไข</button>`}
      ${!editing && product.reviewRequired ? `<button class="btn btn-primary" id="dpMarkResolved" type="button">✓ ยืนยันว่าถูกต้อง (Mark Resolved)</button>` : ""}
      ${editing ? `<span class="dp-editing-badge">โหมดแก้ไข</span>` : ""}
      <span class="dp-resolve-feedback" id="dpResolveFeedback"></span>
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
        <textarea class="dp-reason-text" id="dpReasonText" placeholder="รายละเอียดเพิ่มเติม (ถ้ามี)">${pendingReason && !REASON_PRESETS.includes(pendingReason) ? escapeHtml(pendingReason) : ""}</textarea>
      </div>
      <div class="dp-save-bar">
        <button class="btn" id="dpCancelEdit" type="button">ยกเลิก</button>
        <button class="btn btn-primary" id="dpSaveEdit" type="button">บันทึกการแก้ไข</button>
        <span class="dp-save-feedback" id="dpSaveFeedback"></span>
      </div>
    ` : ""}
    <div class="dp-source-link" id="dpShowPdf">👁 ดูจากเอกสารต้นฉบับ (หน้า ${product.page})</div>
    <div class="dp-history-section">
      <div class="dp-label" style="margin-top:16px;">ประวัติการแก้ไข</div>
      <div id="dpHistory"></div>
    </div>
  `;

  if (focusedField) {
    const restored =
      focusedField === "dpReasonText"
        ? container.querySelector("#dpReasonText")
        : container.querySelector(`.dp-edit-input[data-field="${focusedField}"]`);
    if (restored) {
      restored.focus();
      if (focusedSelectionStart !== null && typeof restored.setSelectionRange === "function") {
        restored.setSelectionRange(focusedSelectionStart, focusedSelectionEnd ?? focusedSelectionStart);
      }
    }
  }

  renderHistory(container.querySelector("#dpHistory"), product.rowId);

  // Opens in the app's existing modal (#modalBackdrop/#modalBox, the same
  // one main.js uses for confirm/error dialogs) rather than the small
  // inline iframe this used to embed directly in the side panel - user
  // request: bigger, but a window, not fullscreen. modal-box-lg is a size
  // modifier only; the dialogs elsewhere keep the normal small modal-box.
  container.querySelector("#dpShowPdf").addEventListener("click", () => {
    const backdrop = document.getElementById("modalBackdrop");
    const box = document.getElementById("modalBox");
    box.classList.add("modal-box-lg");
    box.innerHTML = `
      <div class="modal-pdf-head">
        <h3>เอกสารต้นฉบับ — หน้า ${product.page}</h3>
        <button type="button" class="btn btn-sm" id="dpPdfModalClose">ปิด</button>
      </div>
      <iframe class="evidence-pdf-modal" title="เอกสารต้นฉบับ" src="${api.pdfUrl(product.docId)}#page=${product.page}&view=FitH"></iframe>
    `;
    backdrop.classList.add("open");
    const close = () => {
      backdrop.classList.remove("open");
      box.classList.remove("modal-box-lg");
      box.innerHTML = "";
    };
    box.querySelector("#dpPdfModalClose").addEventListener("click", close);
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); }, { once: true });
  });

  const resolveBtn = container.querySelector("#dpMarkResolved");
  if (resolveBtn) {
    resolveBtn.addEventListener("click", async () => {
      const feedback = container.querySelector("#dpResolveFeedback");
      resolveBtn.disabled = true;
      feedback.textContent = "กำลังยืนยัน...";
      feedback.className = "dp-resolve-feedback";
      try {
        await api.confirmReview(product.rowId);
        document.dispatchEvent(new CustomEvent("product-saved", { detail: { rowId: product.rowId } }));
      } catch (err) {
        feedback.textContent = "ยืนยันไม่สำเร็จ — ยังมีปัญหาที่ต้องแก้ไขก่อน (เช่น รหัสสินค้า/ยอดเงินขัดแย้ง)";
        feedback.className = "dp-resolve-feedback error";
        resolveBtn.disabled = false;
      }
    });
  }

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
        let propagatedCount = 0;
        // expectedUpdatedAt advances after each successful PATCH in this
        // loop - our own second field-edit in the same save is not a
        // conflict, only a change from *someone else* since the row was
        // last loaded/saved is (PR12).
        let expectedUpdatedAt = product.updatedAt;
        for (const [field, rawValue] of Object.entries(pendingEdits)) {
          const numeric = ["weight_qty", "pu_qty", "sku_qty", "unit_price", "amount"].includes(field);
          const value = numeric ? (rawValue === "" ? null : Number(rawValue)) : rawValue;
          const result = await api.patchProduct(product.rowId, field, value, pendingReason || null, expectedUpdatedAt);
          propagatedCount += result?.propagatedCount || 0;
          expectedUpdatedAt = result?.row?.updatedAt ?? expectedUpdatedAt;
        }
        // A name correction also propagates to every other row sharing this
        // barcode (user request: fixing this name should fix the same
        // product wherever else it appears, across other documents) and is
        // saved to Local Verified Master so future documents resolve it
        // too - surfaced here so the user knows it wasn't just this one row.
        feedback.textContent = propagatedCount > 0
          ? `✓ บันทึกแล้ว (แก้ไข ${propagatedCount} รายการที่ตรงกันในเอกสารอื่นด้วย)`
          : "✓ บันทึกแล้ว";
        feedback.className = "dp-save-feedback ok";
        editing = false;
        pendingEdits = {};
        pendingReason = "";
        onDirtyChange(false);
        document.dispatchEvent(new CustomEvent("product-saved", { detail: { rowId: product.rowId } }));
      } catch (err) {
        if (err?.status === 412) {
          // Someone else's edit landed first - the local pending edits are
          // now based on stale data and must not be silently forced through.
          // Reuse the same refresh path a successful save takes, so the
          // panel reopens showing the latest row instead of the stale one.
          feedback.textContent = "มีการแก้ไขข้อมูลนี้จากที่อื่นแล้ว กำลังโหลดข้อมูลล่าสุด...";
          feedback.className = "dp-save-feedback error";
          editing = false;
          pendingEdits = {};
          pendingReason = "";
          onDirtyChange(false);
          document.dispatchEvent(new CustomEvent("product-saved", { detail: { rowId: product.rowId } }));
        } else {
          feedback.textContent = "บันทึกไม่สำเร็จ — ไม่มีการเปลี่ยนแปลงถูกบันทึก";
          feedback.className = "dp-save-feedback error";
          saveBtn.disabled = false;
        }
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
