"""Coverage gap closed (spec Level 6 - "malformed PDF tests"): before this,
nothing in the suite exercised loader/preflight.py at all, even though
it's the module responsible for rejecting non-PDF content, oversized
files, and corrupted PDFs before any content is trusted.
"""
from __future__ import annotations

import pytest

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.loader.preflight import PreflightError, run_preflight


def test_rejects_empty_file(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(PreflightError) as exc:
        run_preflight(path, Settings())
    assert exc.value.code == "PDF_CORRUPTED"


def test_rejects_wrong_magic_bytes(tmp_path):
    path = tmp_path / "notreally.pdf"
    path.write_bytes(b"this is a text file, not a pdf, but has a .pdf extension\n" * 5)
    with pytest.raises(PreflightError) as exc:
        run_preflight(path, Settings())
    assert exc.value.code == "NOT_A_PDF"


def test_rejects_file_over_max_size(tmp_path):
    path = tmp_path / "huge.pdf"
    # Real %PDF- header so the size check (which runs first) is what
    # actually trips, not the magic-byte check.
    path.write_bytes(b"%PDF-1.4\n" + b"0" * 1000)
    settings = Settings(max_file_size_bytes=500)
    with pytest.raises(PreflightError) as exc:
        run_preflight(path, settings)
    assert exc.value.code == "FILE_TOO_LARGE"


def test_rejects_corrupted_pdf_with_valid_header(tmp_path):
    """A file that starts with a real PDF signature but isn't a parseable
    PDF structure - pikepdf must catch this, not just the magic-byte
    check, which would pass it through."""
    path = tmp_path / "corrupted.pdf"
    path.write_bytes(b"%PDF-1.4\n" + b"\x00\x01\x02 not a real pdf body at all" * 20)
    with pytest.raises(PreflightError) as exc:
        run_preflight(path, Settings())
    assert exc.value.code == "PDF_CORRUPTED"


def test_accepts_a_real_minimal_pdf(tmp_path):
    """Regression guard the other direction: a genuinely valid (if
    minimal) single-page PDF must pass preflight cleanly."""
    import pikepdf

    path = tmp_path / "valid.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.save(str(path))

    result = run_preflight(path, Settings())
    assert result.page_count == 1
    assert result.is_encrypted is False
    assert not result.warnings


def test_rejects_too_many_pages(tmp_path):
    import pikepdf

    path = tmp_path / "many_pages.pdf"
    pdf = pikepdf.new()
    for _ in range(3):
        pdf.add_blank_page(page_size=(100, 100))
    pdf.save(str(path))

    settings = Settings(max_pages=2)
    with pytest.raises(PreflightError) as exc:
        run_preflight(path, settings)
    assert exc.value.code == "TOO_MANY_PAGES"
