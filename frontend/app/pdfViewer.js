import { api } from "./api.js";
import { escapeHtml } from "./escape.js";

// Shared by detailPanel.js (view the source page behind one product row)
// and documents.js (PR18: view a document's PDF directly from the
// Documents list, which had no way to see the original file at all before
// this) - opens the app's existing modal (#modalBackdrop/#modalBox, the
// same one main.js uses for confirm/error dialogs) with an embedded PDF
// iframe, rather than each caller building its own inline viewer.
export function openPdfModal(docId, { page, title } = {}) {
  const backdrop = document.getElementById("modalBackdrop");
  const box = document.getElementById("modalBox");
  box.classList.add("modal-box-lg");
  const pageAnchor = page ? `#page=${page}&view=FitH` : "";
  box.innerHTML = `
    <div class="modal-pdf-head">
      <h3>${escapeHtml(title || "เอกสารต้นฉบับ")}</h3>
      <button type="button" class="btn btn-sm" id="pdfModalClose">ปิด</button>
    </div>
    <iframe class="evidence-pdf-modal" title="เอกสารต้นฉบับ" src="${api.pdfUrl(docId)}${pageAnchor}"></iframe>
  `;
  backdrop.classList.add("open");
  const close = () => {
    backdrop.classList.remove("open");
    box.classList.remove("modal-box-lg");
    box.innerHTML = "";
  };
  box.querySelector("#pdfModalClose").addEventListener("click", close);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); }, { once: true });
}
