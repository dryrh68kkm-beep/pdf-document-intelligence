// Every product name/department/article/barcode/remark rendered by this app
// ultimately comes from an untrusted source - PDF text, OCR, or an imported
// master-catalog CSV, all of which can contain arbitrary text - so any value
// interpolated into innerHTML must go through this first. Never applied to
// the markup itself (icons, wrapper tags), only to the data inside it.
export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
