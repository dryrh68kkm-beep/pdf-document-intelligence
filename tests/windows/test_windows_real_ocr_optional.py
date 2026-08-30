"""Optional, non-blocking real-OCR check for the Windows CI job.

Installing a Thai-capable Tesseract reliably via CI package managers on
windows-latest (chocolatey's `tesseract` package, at last check, ships
English data only - a Thai traineddata file is not guaranteed to be
present) is not something this job can depend on without risking flaky,
environment-dependent red builds unrelated to any real regression. Per the
hardening spec, the *smoke/E2E* part of the Windows job
(tests/windows/test_windows_e2e.py) is required; this file is run as a
separate, `continue-on-error: true` step so a missing/incomplete Windows
Tesseract install skips these tests instead of failing the job.

Every test here is a no-op skip when tesseract (or its Thai pack) is not
on PATH, so this file is also harmless to run anywhere else, including
this repo's Linux jobs where Tesseract-with-Thai is already installed and
required.
"""
from __future__ import annotations

import shutil

import pytest

try:
    import pytesseract
except ImportError:  # pragma: no cover - "ocr" extra always installed in CI
    pytesseract = None


def _thai_pack_available() -> bool:
    if shutil.which("tesseract") is None or pytesseract is None:
        return False
    try:
        return "tha" in set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _thai_pack_available(), reason="Tesseract with Thai language pack not available")
def test_health_endpoint_reports_thai_pack_available():
    from pdf_document_intelligence.api.health import check_health
    from pdf_document_intelligence.db.repository import get_repository

    result = check_health(get_repository())
    assert result["ocr"]["thaiLanguagePack"]["available"] is True


@pytest.mark.skipif(not _thai_pack_available(), reason="Tesseract with Thai language pack not available")
def test_real_ocr_on_a_synthetic_image_does_not_crash():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (300, 80), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 25), "SYNTHETIC 12345", fill="black")

    text = pytesseract.image_to_string(img, lang="tha+eng")
    assert isinstance(text, str)
