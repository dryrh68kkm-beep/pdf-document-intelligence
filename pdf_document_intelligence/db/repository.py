"""SQLite repository: the only module that writes SQL. Everything above
this layer (store.py, api/*.py) works with plain dicts, never raw sqlite3
rows or cursors.

Product-row identity across a reprocess: matched by (department, barcode)
falling back to (department, article_code) falling back to (department,
row_index). A matched row keeps its id (so corrections/audit history stay
attached); an unmatched old row is soft-deleted, never hard-deleted, so its
correction history remains inspectable.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

from pdf_document_intelligence.db.connection import get_connection, get_write_lock
from pdf_document_intelligence.db.errors import RowConflictError, RowNotFoundError
from pdf_document_intelligence.db.field_columns import FIELD_TO_COLUMN, NUMERIC_FIELDS
from pdf_document_intelligence.db.migrations import SCHEMA_VERSION, current_version


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


class Repository:
    """Note: `_conn` is looked up fresh on every access rather than cached
    at construction time, so a long-lived singleton `Repository` (like
    `api.store.store.repo`) keeps working correctly across a connection
    swap (used by tests to simulate a server restart, and by
    `db.backup.restore_backup` which reopens the DB file in place)."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._fixed_conn = conn

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._fixed_conn or get_connection()

    # ---------------- documents ----------------

    def create_document(self, doc_id: str, sha256: str, filename: str, file_size: int) -> dict:
        # The read-back must happen inside the same write-lock-held
        # transaction as the INSERT, not after it - two concurrent
        # uploads each call create_document() in their own thread on the
        # same shared connection (see db/connection.py's module docstring),
        # and a read issued after releasing the lock can interleave with
        # the *other* thread's still-in-flight write on that connection.
        # Reproduced live: two concurrent POST /api/documents for the same
        # file, the "winner" thread's post-lock get_document(doc_id) call
        # returned None for the row it had just inserted, crashing
        # document_summary_json() with a bare 500 instead of ever reaching
        # the client with a 200.
        now = _now()
        with get_write_lock(), self._conn:
            self._conn.execute(
                """INSERT INTO documents
                   (id, sha256, filename, file_size, status, progress_stage,
                    uploaded_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'processing', 'queued', ?, ?, ?)""",
                (doc_id, sha256, filename, file_size, now, now, now),
            )
            row = self._conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row)

    def create_document_if_below_processing_cap(
        self, doc_id: str, sha256: str, filename: str, file_size: int, cap: int
    ) -> dict | None:
        """Same insert as create_document(), plus an admission check for
        the processing-queue backlog cap (api/app.py's
        `_MAX_QUEUED_PROCESSING_JOBS`) done in the *same* locked
        transaction as the INSERT, not as a separate earlier read.

        Hardening fix: app.py's own pre-upload `_count_processing_documents()
        >= _MAX_QUEUED_PROCESSING_JOBS` check (kept, unchanged, as a
        fast-fail before spending time streaming a large upload to disk)
        is a plain read with no lock - reproduced under real thread
        concurrency (a burst of uploads well past the cap arriving at
        once), every one of them can observe the count as still under the
        cap before any of their own inserts land, so the cap ends up not
        enforced at all rather than admitting exactly `cap` in flight.
        This method is the actual enforcement point: the COUNT and the
        INSERT happen inside one `get_write_lock()`-held transaction, so
        no two concurrent callers can both observe room for the last slot.
        Returns None (nothing written) if the cap is already met at the
        moment this call takes the lock; the created document dict
        otherwise. The public behavior this closes the race for -
        "too many in flight" still surfaces to the client as the same 503
        with the same message app.py has always returned - is otherwise
        unchanged.
        """
        now = _now()
        with get_write_lock(), self._conn:
            current = self._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE status='processing'"
            ).fetchone()[0]
            if current >= cap:
                return None
            self._conn.execute(
                """INSERT INTO documents
                   (id, sha256, filename, file_size, status, progress_stage,
                    uploaded_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'processing', 'queued', ?, ?, ?)""",
                (doc_id, sha256, filename, file_size, now, now, now),
            )
            row = self._conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row)

    def find_document_by_sha256(self, sha256: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM documents WHERE sha256 = ? AND deleted_at IS NULL", (sha256,)
        ).fetchone()
        return dict(row) if row else None

    def get_document(self, doc_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return dict(row) if row else None

    def list_documents(self, include_deleted: bool = False) -> list[dict]:
        q = "SELECT * FROM documents"
        if not include_deleted:
            q += " WHERE deleted_at IS NULL"
        q += " ORDER BY uploaded_at DESC"
        return [dict(r) for r in self._conn.execute(q)]

    def update_progress(self, doc_id: str, stage: str, current: int, total: int) -> None:
        with get_write_lock(), self._conn:
            self._conn.execute(
                """UPDATE documents SET progress_stage=?, progress_current=?, progress_total=?,
                   updated_at=? WHERE id=?""",
                (stage, current, total, _now(), doc_id),
            )

    def set_document_complete(self, doc_id: str, page_count: int, meta: dict) -> None:
        with get_write_lock(), self._conn:
            self._set_document_complete_sql(doc_id, page_count, meta)

    def _set_document_complete_sql(self, doc_id: str, page_count: int, meta: dict) -> None:
        """Caller must already hold the write transaction - see
        `_replace_document_rows_sql`'s docstring for why."""
        self._conn.execute(
            """UPDATE documents SET status='complete', page_count=?, meta_json=?,
               error=NULL, updated_at=? WHERE id=?""",
            (page_count, json.dumps(meta, ensure_ascii=False), _now(), doc_id),
        )

    def complete_document_with_rows(self, doc_id: str, page_count: int, meta: dict, new_rows: list[dict]) -> dict:
        """Atomically marks a document complete and writes its product rows
        in one transaction. Fixes a real crash window (L2-003, reproduced):
        `set_document_complete` and `replace_document_rows` used to be two
        independent transactions - if the process was killed between the
        two commits (not a Python exception, which the caller's except
        block would recover from by marking the document 'error' - an
        actual kill/crash/power loss), the document was left permanently
        showing status='complete' with zero or stale product_rows, with no
        automatic way to detect or recover from it.

        Also guards against a delete/reprocess race (L3-002, reproduced): a
        background job started before the user deleted this document has
        no way to know that happened, and used to insert its product_rows
        anyway - those rows aren't hidden by the document being gone from
        `list_documents()` (build_dashboard_state sums *all* product_rows,
        not only ones whose parent document is still active), so a
        deleted document's weight/PU/SKU totals kept silently counting
        toward the dashboard grand totals. Checked and skipped inside the
        same transaction as the write, so this is race-free against a
        delete happening concurrently.
        """
        with get_write_lock(), self._conn:
            doc = self._conn.execute(
                "SELECT deleted_at FROM documents WHERE id=?", (doc_id,)
            ).fetchone()
            if doc is None or doc["deleted_at"] is not None:
                return {"skipped": True, "reason": "document was deleted before processing finished"}
            self._set_document_complete_sql(doc_id, page_count, meta)
            return self._replace_document_rows_sql(doc_id, new_rows)

    def set_document_error(self, doc_id: str, error: str) -> None:
        with get_write_lock(), self._conn:
            self._conn.execute(
                "UPDATE documents SET status='error', error=?, updated_at=? WHERE id=?",
                (error, _now(), doc_id),
            )

    def try_start_processing(self, doc_id: str) -> bool:
        """Atomically transition a document into 'processing' only if it
        isn't already - the `AND status != 'processing'` guard and the
        write lock together close the check-then-act race that a plain
        "read status, then call set_document_processing()" would leave
        open (two reprocess requests racing to submit a second worker for
        the same document, exactly like the SHA-256 unique index already
        closes the equivalent race for concurrent duplicate uploads).
        Returns whether this call won the race and should proceed to
        submit a processing job; False means a processing job for this
        document is already in flight."""
        with get_write_lock(), self._conn:
            cur = self._conn.execute(
                """UPDATE documents SET status='processing', error=NULL,
                   progress_stage='queued', progress_current=0, progress_total=0,
                   updated_at=? WHERE id=? AND status != 'processing'""",
                (_now(), doc_id),
            )
        return cur.rowcount > 0

    def soft_delete_document(self, doc_id: str) -> bool:
        with get_write_lock(), self._conn:
            cur = self._conn.execute(
                "UPDATE documents SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL",
                (_now(), _now(), doc_id),
            )
            self._conn.execute(
                "UPDATE product_rows SET deleted_at=?, updated_at=? WHERE document_id=? AND deleted_at IS NULL",
                (_now(), _now(), doc_id),
            )
        return cur.rowcount > 0

    # ---------------- product rows ----------------

    def replace_document_rows(self, document_id: str, new_rows: list[dict]) -> dict:
        with get_write_lock(), self._conn:
            return self._replace_document_rows_sql(document_id, new_rows)

    def _replace_document_rows_sql(self, document_id: str, new_rows: list[dict]) -> dict:
        """Batch-inserts extraction output for a document. On first process
        this is a plain batch insert. On reprocess, matches new rows against
        existing (non-deleted) rows by (department, barcode/article/row_index)
        and UPDATEs extraction-derived columns in place so id, and therefore
        correction history, is preserved; a field that already carries a
        correction (resolution_status == 'CORRECTED') is left untouched and
        reported back rather than silently overwritten. Old rows with no
        match in the new extraction are soft-deleted, never hard-deleted.

        Caller must already hold the write transaction (`with self._conn:`)
        - this method issues no commit/rollback of its own, so it can be
        composed with other writes (see `complete_document_with_rows`) into
        one atomic transaction.

        Matching uses a FIFO queue per key, not a single dict slot: two
        rows can legitimately share the same (department, barcode) - a real
        document can list the same article twice as separate line items
        (verified against the BPDC golden sample) - so a plain dict would
        let the second one silently overwrite the first's match, causing
        the first to look "gone" from the new extraction and get
        soft-deleted, while both new rows updated the single surviving old
        row instead of one each.
        """
        now = _now()
        existing = [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM product_rows WHERE document_id=? AND deleted_at IS NULL",
                (document_id,),
            )
        ]

        def match_key(r: dict) -> tuple:
            if r.get("barcode"):
                return ("bc", r["department"], r["barcode"])
            if r.get("article_code"):
                return ("art", r["department"], r["article_code"])
            return ("idx", r["department"], r["row_index"])

        existing_by_key: dict[tuple, deque] = defaultdict(deque)
        for r in existing:
            existing_by_key[match_key(r)].append(r)

        matched_ids: set[str] = set()
        preserved_corrections: list[dict] = []
        inserted = 0
        updated = 0

        for nr in new_rows:
            key = match_key(nr)
            bucket = existing_by_key.get(key)
            old = bucket.popleft() if bucket else None
            if old:
                matched_ids.add(old["id"])
                corrected_fields = set(json.loads(old.get("corrected_fields_json") or "[]"))
                row_update = dict(nr)
                for f in corrected_fields:
                    # `corrected_fields` stores API-level field names (what
                    # api/review.py's PATCH accepts, e.g. "name",
                    # "article"), not DB column names - most are identical
                    # (weight_qty, department, ...) but "name" ->
                    # resolved_product_name and "article" -> article_code
                    # are not, so comparing the raw name against
                    # `row_update` (which is column-keyed, from
                    # api/rows.py::flatten_row) silently missed those two
                    # and let reprocess overwrite the correction with no
                    # audit record of the reversal. Map through the same
                    # FIELD_TO_COLUMN table api/review.py itself uses.
                    column = FIELD_TO_COLUMN.get(f, f)
                    if column in row_update:
                        row_update[column] = old.get(column)
                        preserved_corrections.append(
                            {"row_id": old["id"], "field": f, "note": "reprocess did not override corrected field"}
                        )
                self._conn.execute(
                    """UPDATE product_rows SET
                        source_page=?, raw_product_name=?, ocr_product_name=?,
                        resolved_product_name=?, weight_qty=?, pu_qty=?, sku_qty=?,
                        unit=?, unit_price=?, amount=?, confidence=?, confidence_band=?,
                        resolution_status=?, review_required=?, review_reasons=?,
                        suspected_non_product=?, non_product_reasons=?, fields_json=?,
                        updated_at=?
                       WHERE id=?""",
                    (
                        row_update["source_page"], row_update["raw_product_name"],
                        row_update["ocr_product_name"], row_update["resolved_product_name"],
                        row_update["weight_qty"], row_update["pu_qty"], row_update["sku_qty"],
                        row_update["unit"], row_update["unit_price"], row_update["amount"],
                        row_update["confidence"], row_update["confidence_band"],
                        row_update["resolution_status"], int(row_update["review_required"]),
                        json.dumps(row_update.get("review_reasons") or []),
                        int(row_update["suspected_non_product"]),
                        json.dumps(row_update.get("non_product_reasons") or []),
                        json.dumps(row_update["fields"], ensure_ascii=False),
                        now, old["id"],
                    ),
                )
                updated += 1
            else:
                row_id = new_id()
                self._conn.execute(
                    """INSERT INTO product_rows
                       (id, document_id, source_page, row_index, department, barcode,
                        article_code, identity_code, raw_product_name, ocr_product_name,
                        resolved_product_name, weight_qty, pu_qty, sku_qty, unit,
                        unit_price, amount, confidence, confidence_band, resolution_status,
                        review_required, review_reasons, suspected_non_product,
                        non_product_reasons, fields_json, corrected_fields_json,
                        created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row_id, document_id, nr["source_page"], nr["row_index"], nr["department"],
                        nr.get("barcode"), nr.get("article_code"), nr.get("identity_code"),
                        nr.get("raw_product_name"), nr.get("ocr_product_name"),
                        nr.get("resolved_product_name"), nr.get("weight_qty"), nr.get("pu_qty"),
                        nr.get("sku_qty"), nr.get("unit"), nr.get("unit_price"), nr.get("amount"),
                        nr.get("confidence"), nr.get("confidence_band"), nr.get("resolution_status", "OCR"),
                        int(nr.get("review_required", False)), json.dumps(nr.get("review_reasons") or []),
                        int(nr.get("suspected_non_product", False)),
                        json.dumps(nr.get("non_product_reasons") or []),
                        json.dumps(nr["fields"], ensure_ascii=False), "[]",
                        now, now,
                    ),
                )
                inserted += 1

        stale_ids = [r["id"] for r in existing if r["id"] not in matched_ids]
        for stale_id in stale_ids:
            self._conn.execute(
                "UPDATE product_rows SET deleted_at=?, updated_at=? WHERE id=?",
                (now, now, stale_id),
            )

        return {
            "inserted": inserted,
            "updated": updated,
            "soft_deleted": len(stale_ids),
            "preserved_corrections": preserved_corrections,
        }

    def get_product_row(self, row_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM product_rows WHERE id=?", (row_id,)).fetchone()
        return dict(row) if row else None

    def list_product_rows(
        self, document_id: str | None = None, review_required: bool | None = None,
        include_deleted: bool = False,
    ) -> list[dict]:
        q = "SELECT * FROM product_rows WHERE 1=1"
        params: list[Any] = []
        if not include_deleted:
            q += " AND deleted_at IS NULL"
        if document_id:
            q += " AND document_id=?"
            params.append(document_id)
        if review_required is not None:
            q += " AND review_required=?"
            params.append(int(review_required))
        q += " ORDER BY document_id, row_index"
        return [dict(r) for r in self._conn.execute(q, params)]

    def update_product_row_field(
        self, row_id: str, field_name: str, old_value: Any, new_value: Any,
        column_updates: dict, reason: str | None, source: str = "LOCAL_USER",
        expected_updated_at: str | None = None,
    ) -> dict:
        """Writes one corrected field + its audit record atomically.

        PR12 fix: the caller used to SELECT the row, compare its
        `updated_at` to `expected_updated_at` in Python, and only *then*
        call this method to UPDATE - two concurrent callers could both
        pass that compare (both reading the same pre-write `updated_at`)
        before either one's UPDATE ran, so the second one to actually
        write silently clobbered the first with no error. The conditional
        UPDATE below (`WHERE ... AND updated_at=?`) makes the compare and
        the write one atomic SQL statement instead of two Python steps:
        whichever caller's UPDATE actually lands first changes `updated_at`
        out from under the other, so the second one's own conditional
        UPDATE matches zero rows and fails - `cursor.rowcount` is SQLite's
        own authoritative answer, not a value this process ever had to
        compute from a stale read. When `expected_updated_at` is None
        (caller doesn't have a version token) this behaves exactly as
        before: an unconditional update.
        """
        now = _now()
        with get_write_lock(), self._conn:
            row = self.get_product_row(row_id)
            if row is None or row.get("deleted_at") is not None:
                raise RowNotFoundError(row_id)

            corrected_fields = set(json.loads(row.get("corrected_fields_json") or "[]"))
            corrected_fields.add(field_name)

            set_clauses = ", ".join(f"{k}=?" for k in column_updates)
            values = list(column_updates.values())
            params = [*values, json.dumps(sorted(corrected_fields)), now, row_id]
            where = "WHERE id=? AND deleted_at IS NULL"
            if expected_updated_at is not None:
                where += " AND updated_at=?"
                params.append(expected_updated_at)

            cur = self._conn.execute(
                f"""UPDATE product_rows SET {set_clauses}, corrected_fields_json=?,
                    resolution_status='CORRECTED', updated_at=? {where}""",
                params,
            )
            if cur.rowcount == 0:
                current = self.get_product_row(row_id)
                if current is None or current.get("deleted_at") is not None:
                    raise RowNotFoundError(row_id)
                raise RowConflictError(current)

            correction_id = new_id()
            self._conn.execute(
                """INSERT INTO corrections
                   (id, product_row_id, field_name, old_value, new_value, reason, source, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (correction_id, row_id, field_name, str(old_value) if old_value is not None else None,
                 str(new_value) if new_value is not None else None, reason, source, now),
            )
        return {"correction_id": correction_id}

    def undo_correction(self, correction_id: str, source: str = "LOCAL_USER") -> dict:
        now = _now()
        with get_write_lock(), self._conn:
            corr = self._conn.execute("SELECT * FROM corrections WHERE id=?", (correction_id,)).fetchone()
            if not corr:
                raise ValueError("correction not found")
            corr = dict(corr)
            row_id = corr["product_row_id"]
            field = corr["field_name"]
            revert_value_str = corr["old_value"]
            column = FIELD_TO_COLUMN.get(field)
            revert_value: Any = revert_value_str
            if column and field in NUMERIC_FIELDS and revert_value_str is not None:
                revert_value = float(revert_value_str)

            if column:
                self._conn.execute(
                    f"UPDATE product_rows SET {column}=?, updated_at=? WHERE id=?",
                    (revert_value, now, row_id),
                )

            undo_id = new_id()
            self._conn.execute(
                """INSERT INTO corrections
                   (id, product_row_id, field_name, old_value, new_value, reason, source, undo_of_id, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (undo_id, row_id, field, corr["new_value"], revert_value_str, "undo", source, correction_id, now),
            )
        return {"undo_id": undo_id, "field": field, "reverted_to": revert_value, "product_row_id": row_id}

    def list_corrections(self, row_id: str) -> list[dict]:
        return [
            dict(r)
            for r in self._conn.execute(
                "SELECT * FROM corrections WHERE product_row_id=? ORDER BY created_at ASC", (row_id,)
            )
        ]

    # ---------------- local product master ----------------

    def find_local_master_by_barcode(self, barcode: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM local_product_master WHERE barcode=?", (barcode,)
        ).fetchone()
        return dict(row) if row else None

    def add_local_master(
        self, barcode: str, product_name: str, department: str | None,
        unit: str | None, article_code: str | None, source_document_id: str | None,
    ) -> dict:
        # Fast-fail only, same as apply_correction()'s pre-lock check in
        # api/review.py - not authoritative. The INSERT below is what
        # actually decides, and its (re-)read-back happens inside the same
        # locked transaction (see create_document()'s docstring for why an
        # unlocked read-after-write on the shared connection is unsafe).
        existing = self.find_local_master_by_barcode(barcode)
        if existing:
            return {"created": False, "entry": existing}
        now = _now()
        entry_id = new_id()
        with get_write_lock(), self._conn:
            current = self._conn.execute(
                "SELECT * FROM local_product_master WHERE barcode=?", (barcode,)
            ).fetchone()
            if current:
                return {"created": False, "entry": dict(current)}
            self._conn.execute(
                """INSERT INTO local_product_master
                   (id, barcode, article_code, product_name, department, unit,
                    source_document_id, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (entry_id, barcode, article_code, product_name, department, unit,
                 source_document_id, now, now),
            )
            row = self._conn.execute(
                "SELECT * FROM local_product_master WHERE barcode=?", (barcode,)
            ).fetchone()
        return {"created": True, "entry": dict(row)}

    def upsert_local_master_name(self, barcode: str, product_name: str, source_document_id: str | None) -> dict:
        """Unlike add_local_master() (insert-only, never overwrites), this
        always applies the given name - a manual correction to a barcode's
        name (user request: correcting one row's name should also fix the
        same product's name wherever else its barcode appears) is a
        deliberate override, so an existing Local Master entry's name must
        actually change too, not be left stale."""
        now = _now()
        with get_write_lock(), self._conn:
            existing = self.find_local_master_by_barcode(barcode)
            if existing:
                self._conn.execute(
                    "UPDATE local_product_master SET product_name=?, updated_at=? WHERE barcode=?",
                    (product_name, now, barcode),
                )
            else:
                self._conn.execute(
                    """INSERT INTO local_product_master
                       (id, barcode, article_code, product_name, department, unit,
                        source_document_id, created_at, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (new_id(), barcode, None, product_name, None, None, source_document_id, now, now),
                )
            row = self._conn.execute(
                "SELECT * FROM local_product_master WHERE barcode=?", (barcode,)
            ).fetchone()
        return dict(row)

    def list_product_rows_by_barcode(self, barcode: str, exclude_row_id: str | None = None) -> list[dict]:
        """Every non-deleted row across every document sharing this
        barcode - used to propagate a name correction (user request) to
        the same product wherever else it appears, not just the one row
        being edited."""
        q = "SELECT * FROM product_rows WHERE barcode=? AND deleted_at IS NULL"
        params: list[Any] = [barcode]
        if exclude_row_id:
            q += " AND id != ?"
            params.append(exclude_row_id)
        return [dict(r) for r in self._conn.execute(q, params)]

    def list_local_master(self, search: str | None = None) -> list[dict]:
        q = "SELECT * FROM local_product_master"
        params: list[Any] = []
        if search:
            q += " WHERE barcode LIKE ? OR article_code LIKE ? OR product_name LIKE ?"
            like = f"%{search}%"
            params = [like, like, like]
        q += " ORDER BY updated_at DESC"
        return [dict(r) for r in self._conn.execute(q, params)]

    def count_local_master(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM local_product_master").fetchone()[0]

    # ---------------- health ----------------

    def reset_all_for_tests(self) -> None:
        with get_write_lock(), self._conn:
            self._conn.execute("DELETE FROM corrections")
            self._conn.execute("DELETE FROM product_rows")
            self._conn.execute("DELETE FROM local_product_master")
            self._conn.execute("DELETE FROM documents")

    def health(self) -> dict:
        try:
            self._conn.execute("SELECT 1").fetchone()
            db_ok = True
        except sqlite3.Error:
            db_ok = False
        return {
            "status": "ok" if db_ok else "error",
            "schemaVersion": current_version(self._conn),
            "expectedSchemaVersion": SCHEMA_VERSION,
        }


def get_repository() -> Repository:
    """Returns a Repository that always resolves the connection lazily via
    the module-level singleton (see Repository._conn) - not one pinned to
    whatever connection happens to be live right now."""
    return Repository(None)
