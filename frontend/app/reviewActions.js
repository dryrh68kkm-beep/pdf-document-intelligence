import { api } from "./api.js";

// Shared by products.js and review.js (PR16/PR17): both tables let a user
// mark a still-needs-review row resolved with one click, without opening
// the detail panel first - kept in one place instead of duplicating the
// confirm-dialog/api-call/error-handling block in both views.
export function confirmMarkResolved(store, row) {
  store.set({
    confirmDialog: {
      title: "ยืนยันว่าถูกต้อง (Mark Resolved)",
      message: `ยืนยันว่า "${row.fields?.name?.value || row.fields?.article?.value || "รายการนี้"}" ถูกต้อง ไม่ต้องตรวจสอบอีก?`,
      onConfirm: async () => {
        try {
          await api.confirmReview(row.rowId);
          await store.refreshAll();
        } catch (err) {
          store.set({
            errorDialog: {
              title: "ยืนยันไม่สำเร็จ",
              message: String(err?.message || err),
              diagnosticId: err?.diagnosticId,
            },
          });
          document.dispatchEvent(new CustomEvent("show-error"));
        }
      },
    },
  });
  document.dispatchEvent(new CustomEvent("show-confirm"));
}
