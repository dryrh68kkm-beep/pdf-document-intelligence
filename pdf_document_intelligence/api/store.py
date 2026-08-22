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
from datetime import datetime

from pdf_document_intelligence.api.rows import prepare_flat_rows
from pdf_document_intelligence.db.paths import get_pdf_path
from pdf_document_intelligence.db.repository import Repository, get_repository, new_id
from pdf_document_intelligence.models.document import DocumentResult
from pdf_document_intelligence.quality.score import score_quality


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
        return self._repo.get_document(doc_id)

    def get_pdf_bytes(self, doc_id: str) -> bytes | None:
        path = get_pdf_path(doc_id)
        return path.read_bytes() if path.exists() else None

    def list(self) -> list[dict]:
        return self._repo.list_documents()

    def remove(self, doc_id: str) -> bool:
        return self._repo.soft_delete_document(doc_id)

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
