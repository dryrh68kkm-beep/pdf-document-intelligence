"""PR8: a preflight rejection must not look like a successfully processed
document.

Before this, process_document() caught PreflightError internally and
returned a "successful" DocumentResult with 0 pages, 0 confidence, and
status="MANUAL_REVIEW_REQUIRED" - the exact same status value a document
that *was* processed but scored low confidence gets. The caller
(api/app.py's _run_processing) had no way to tell the two apart, so a
corrupted/password-protected/oversized upload silently landed in the DB as
status='complete' and showed up in the UI as a normal, ready-to-use
document with zero data - not as a failure. Letting PreflightError
propagate lets the existing failed-processing path do its job.
"""
from __future__ import annotations

import pytest

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.loader.preflight import PreflightError
from pdf_document_intelligence.pipeline.orchestrator import process_document


def test_process_document_raises_preflight_error_for_corrupted_pdf(tmp_path):
    path = tmp_path / "corrupted.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"\x00\x01\x02 not a real pdf body at all" * 20)

    with pytest.raises(PreflightError) as exc:
        process_document(path, settings=Settings())
    assert exc.value.code == "PDF_CORRUPTED"


def test_process_document_raises_preflight_error_for_empty_file(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")

    with pytest.raises(PreflightError) as exc:
        process_document(path, settings=Settings())
    assert exc.value.code == "PDF_CORRUPTED"


def test_process_document_raises_preflight_error_for_non_pdf(tmp_path):
    path = tmp_path / "notreally.pdf"
    path.write_bytes(b"this is a text file, not a pdf, but has a .pdf extension\n" * 5)

    with pytest.raises(PreflightError) as exc:
        process_document(path, settings=Settings())
    assert exc.value.code == "NOT_A_PDF"
