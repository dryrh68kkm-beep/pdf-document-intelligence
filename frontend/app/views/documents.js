import { api } from "../api.js";

export function renderDocuments(container, store) {
  const { documents } = store.state;
  container.innerHTML = `
    <div class="workspace-header">
      <div class="workspace-title">Documents</div>
      <div class="workspace-sub">${documents.length} ไฟล์</div>
    </div>
    <div id="docList"></div>
  `;
  const list = container.querySelector("#docList");

  if (!documents.length) {
    list.innerHTML = `<div class="empty-state"><div class="icon">📄</div><div class="title">ยังไม่มีเอกสาร</div></div>`;
    return;
  }

  documents.forEach((doc) => {
    const row = document.createElement("div");
    row.className = "doc-row";
    const statusText =
      doc.status === "complete"
        ? `✓ ${doc.rowCount ?? 0} rows · ${doc.pages ?? "?"} pages · confidence ${doc.confidence ?? "?"}%`
        : doc.status === "error"
        ? `อ่านไม่สำเร็จ: ${doc.error || "unknown error"}`
        : `${doc.progress.stage} ${doc.progress.total ? `(${doc.progress.current}/${doc.progress.total})` : ""}`;
    row.innerHTML = `
      <span class="status-dot ${doc.status}"></span>
      <div>
        <div class="doc-name">${doc.filename}</div>
        <div class="doc-meta">${statusText}</div>
      </div>
      <div class="doc-actions">
        ${doc.status !== "processing" ? `<button class="btn btn-sm" data-action="reprocess">Reprocess</button>` : ""}
        <button class="btn btn-sm" data-action="remove">Remove</button>
      </div>
    `;
    row.querySelector('[data-action="reprocess"]')?.addEventListener("click", async () => {
      await api.reprocessDocument(doc.id);
      await store.refreshAll();
    });
    row.querySelector('[data-action="remove"]').addEventListener("click", () => {
      store.set({
        confirmDialog: {
          title: `ลบ ${doc.filename}?`,
          message: "ข้อมูลของไฟล์นี้จะถูกลบออกจาก Dashboard และคำนวณยอดใหม่ทันที",
          onConfirm: async () => {
            await api.deleteDocument(doc.id);
            await store.refreshAll();
          },
        },
      });
      document.dispatchEvent(new CustomEvent("show-confirm"));
    });
    list.appendChild(row);
  });
}
