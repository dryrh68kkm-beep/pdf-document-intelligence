"""In-memory, thread-safe multi-document store.

Persistence beyond the process lifetime (IndexedDB / a real DB) is P2 per
the app spec's own priority ordering — this store is the P0/P1 substrate:
correct multi-document state, SHA-256 dedup, and per-document progress,
without yet surviving a server restart.
"""
from __future__ import annotations

import hashlib
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

from pdf_document_intelligence.models.document import DocumentResult

DocumentStatus = Literal["processing", "complete", "error"]


@dataclass
class ProgressState:
    stage: str = "queued"
    current: int = 0
    total: int = 0


@dataclass
class DocumentEntry:
    id: str
    filename: str
    sha256: str
    uploaded_at: datetime
    status: DocumentStatus
    pdf_bytes: bytes
    progress: ProgressState = field(default_factory=ProgressState)
    result: DocumentResult | None = None
    error: str | None = None


class DocumentStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._docs: dict[str, DocumentEntry] = {}

    def find_by_hash(self, sha256: str) -> DocumentEntry | None:
        with self._lock:
            for doc in self._docs.values():
                if doc.sha256 == sha256:
                    return doc
        return None

    def create(self, filename: str, pdf_bytes: bytes) -> DocumentEntry:
        sha256 = hashlib.sha256(pdf_bytes).hexdigest()
        doc_id = str(uuid.uuid4())
        entry = DocumentEntry(
            id=doc_id,
            filename=filename,
            sha256=sha256,
            uploaded_at=datetime.now(timezone.utc),
            status="processing",
            pdf_bytes=pdf_bytes,
        )
        with self._lock:
            self._docs[doc_id] = entry
        return entry

    def get(self, doc_id: str) -> DocumentEntry | None:
        with self._lock:
            return self._docs.get(doc_id)

    def list(self) -> list[DocumentEntry]:
        with self._lock:
            return sorted(self._docs.values(), key=lambda d: d.uploaded_at, reverse=True)

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            return self._docs.pop(doc_id, None) is not None

    def set_progress(self, doc_id: str, stage: str, current: int, total: int) -> None:
        with self._lock:
            doc = self._docs.get(doc_id)
            if doc:
                doc.progress = ProgressState(stage=stage, current=current, total=total)

    def set_complete(self, doc_id: str, result: DocumentResult) -> None:
        with self._lock:
            doc = self._docs.get(doc_id)
            if doc:
                doc.status = "complete"
                doc.result = result

    def set_error(self, doc_id: str, error: str) -> None:
        with self._lock:
            doc = self._docs.get(doc_id)
            if doc:
                doc.status = "error"
                doc.error = error


store = DocumentStore()
