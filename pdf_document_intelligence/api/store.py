"""Persistent, SQLite-backed multi-document store (replaces the old
in-memory dict). Document metadata + product rows survive a server
restart; the PDF bytes themselves live as files under the data dir
(`db/paths.get_pdf_path`) rather than as SQLite BLOBs, so the DB file
stays small regardless of how many/how large the source PDFs are.

Callers (app.py, aggregate.py, serialize.py) get back plain dicts, never
raw sqlite3 rows - the shape returned here is the contract.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from pdf_document_intelligence.api.rows import prepare_flat_rows
from pdf_document_intelligence.db.paths import get_pdf_path
from pdf_document_intelligence.db.repository import Repository, get_repository, new_id
from pdf_document_intelligence.models.document import DocumentResult
from pdf_document_intelligence.quality.score import score_quality

_logger = logging.getLogger("pdf_document_intelligence")


class DocumentStore:
    def __init__(self, repo: Repository | None = None) -> None:
        self._repo = repo or get_repository()

    @property
    def repo(self) -> Repository:
        return self._repo

    def find_by_hash(self, sha256: str) -> dict | None:
        return self._repo.find_document_by_sha256(sha256)

    def create(self, filename: str, pdf_bytes: bytes) -> dict:
        sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        doc_id = new_id()
        get_pdf_path(doc_id).write_bytes(pdf_bytes)
        return self._repo.create_document(doc_id, sha256, filename, len(pdf_bytes))

    def get(self, doc_id: str) -> dict | None:
        """The active-document lookup every API endpoint should use: a
        deleted document must behave exactly like one that never existed
        (detail, PDF, reprocess, export all 404) rather than staying
        reachable by ID forever. `list()` already filtered deleted
        documents out; this brings the single-document lookup in line
        with it instead of leaving direct-by-ID access as a bypass."""
        doc = self._repo.get_document(doc_id)
        if doc is None or doc.get("deleted_at") is not None:
            return None
        return doc

    def get_active_product_row(self, row_id: str) -> dict | None:
        """A product row must be just as unreachable as its parent
        document once that document is deleted - soft_delete_document
        already cascades deleted_at onto the row itself, so checking the
        row's own deleted_at (rather than re-fetching the document) is
        enough and avoids a second query."""
        row = self._repo.get_product_row(row_id)
        if row is None or row.get("deleted_at") is not None:
            return None
        return row

    def get_pdf_bytes(self, doc_id: str) -> bytes | None:
        path = get_pdf_path(doc_id)
        return path.read_bytes() if path.exists() else None

    def list(self) -> list[dict]:
        return self._repo.list_documents()

    def remove(self, doc_id: str) -> bool:
        """Soft-deletes the DB record (document + its product rows, so
        correction history stays inspectable for forensic purposes rather
        than being hard-deleted) and purges the source PDF from disk - a
        deleted document must not just disappear from listings while its
        file and data stay fully readable by ID underneath. A file already
        missing is not an error (nothing left to purge); an actual OS
        failure to remove it is logged rather than raised; either way the
        document is already gone from every API's perspective via
        `get()`/`list()`, so a stray file failing to unlink is a disk
        clean-up problem, not a reason to fail the user's delete action."""
        removed = self._repo.soft_delete_document(doc_id)
        if removed:
            try:
                get_pdf_path(doc_id).unlink(missing_ok=True)
            except OSError as exc:
                _logger.warning("Failed to purge PDF for deleted document %s: %s", doc_id, exc)
        return removed

    def mark_reprocessing(self, doc_id: str) -> None:
        self._repo.set_document_processing(doc_id)

    def set_progress(self, doc_id: str, stage: str, current: int, total: int) -> None:
        self._repo.update_progress(doc_id, stage, current, total)

    def set_complete(self, doc_id: str, result: DocumentResult) -> dict:
        quality = score_quality(result.tables, result.validation)
        meta = {
            "confidence": result.confidence,
            "statusDocument": result.status,
            "reconciled": result.validation.reconciled,
            "quality": quality.model_dump(),
            "engineVersion": result.engine_version,
            "ocrEngineVersion": result.ocr_engine_version,
            "templateVersion": result.template_version,
            "processingLog": [
                {
                    "step": e.step, "detail": e.detail,
                    "durationMs": round(e.duration_ms, 1) if e.duration_ms else None,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in result.processing_log
            ],
            "pages": result.pages,
            "documentType": result.document_type,
            "parserVersion": result.parser_version,
            "documentDate": result.document_date.isoformat() if result.document_date else None,
            "documentDateEvidence": (
                {
                    "raw": result.document_date_raw,
                    "label": result.document_date_label,
                    "page": result.document_date_page,
                    "source": "pdf_text",
                }
                if result.document_date
                else None
            ),
            "validationIssues": [
                {
                    "severity": i.severity, "code": i.code, "table": i.table,
                    "rowIndex": i.row_index, "field": i.field, "message": i.message,
                }
                for i in [*result.validation.errors, *result.validation.warnings]
            ],
        }
        flat_rows = prepare_flat_rows(doc_id, result, self._repo)
        return self._repo.complete_document_with_rows(doc_id, result.pages, meta, flat_rows)

    def set_error(self, doc_id: str, error: str) -> None:
        self._repo.set_document_error(doc_id, error)

    def reset_for_tests(self) -> None:
        self._repo.reset_all_for_tests()


store = DocumentStore()
