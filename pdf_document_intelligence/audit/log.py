"""Shared structured processing-log writer.

Every pipeline stage appends to the same in-memory log via `ProcessingLog`,
which becomes `DocumentResult.processing_log` (proposal §37 audit trail).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from pdf_document_intelligence.models.document import ProcessingLogEntry


class ProcessingLog:
    def __init__(self) -> None:
        self._entries: list[ProcessingLogEntry] = []

    def step(self, name: str, detail: str = "") -> "_StepTimer":
        return _StepTimer(self, name, detail)

    def record(self, step: str, detail: str, duration_ms: float | None = None) -> None:
        self._entries.append(
            ProcessingLogEntry(
                step=step,
                detail=detail,
                timestamp=datetime.now(timezone.utc),
                duration_ms=duration_ms,
            )
        )

    @property
    def entries(self) -> list[ProcessingLogEntry]:
        return list(self._entries)


class _StepTimer:
    def __init__(self, log: ProcessingLog, name: str, detail: str) -> None:
        self._log = log
        self._name = name
        self._detail = detail
        self._start = 0.0

    def __enter__(self) -> "_StepTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        duration_ms = (time.monotonic() - self._start) * 1000
        detail = self._detail
        if exc is not None:
            detail = f"{detail} FAILED: {exc}".strip()
        self._log.record(self._name, detail, duration_ms)

    def set_detail(self, detail: str) -> None:
        self._detail = detail
