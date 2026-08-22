"""Synthetic end-to-end regression coverage for both supported layouts.

The fixtures are generated at runtime from invented values only; no real
company/user PDF or derived business data is committed to the repository.
"""
from __future__ import annotations

import subprocess

import pytest
from PIL import Image, ImageDraw, ImageFont
import pytesseract

from pdf_document_intelligence.extract.ocr import ocr_region
from pdf_document_intelligence.pipeline.orchestrator import process_document
from tests.synthetic_pdf import make_bigc_pdf, make_bpdc_pdf


def _first_row(result):
    assert result.tables
    assert result.tables[0].rows
    return result.tables[0].rows[0]


def test_bigc_synthetic_pdf_regression(tmp_path):
    path = make_bigc_pdf(tmp_path / "synthetic_bigc.pdf")
    result = process_document(path)

    assert result.document_type == "packing_list_bigc_cdc"
    assert result.pages == 1
    assert result.validation.reconciled is True
    assert result.validation.errors == []

    row = _first_row(result)
    assert row.fields["dn_no"].value == "100001"
    assert row.fields["article"].value == "1234567-89-012"
    assert row.fields["barcode"].value == "9990000000001"
    assert row.fields["weight_qty"].value == 1.5
    assert row.fields["pu_qty"].value == 2
    assert row.fields["sku_qty"].value == 3


def test_bpdc_synthetic_pdf_regression(tmp_path):
    path = make_bpdc_pdf(tmp_path / "synthetic_bpdc.pdf")
    result = process_document(path)

    assert result.document_type == "packing_list_bpdc"
    assert result.pages == 1
    assert result.validation.reconciled is True
    assert result.validation.errors == []

    row = _first_row(result)
    assert row.fields["dn_no"].value == "110001"
    assert row.fields["article"].value == "7654321-98-210"
    assert row.fields["barcode"].value == "9990000000002"
    assert row.fields["weight_qty"].value == 2.5
    assert row.fields["pu_qty"].value == 4
    assert row.fields["sku_qty"].value == 5


def _font_path() -> str:
    path = subprocess.check_output(
        ["fc-match", "-f", "%{file}", "Noto Sans Thai"], text=True
    ).strip()
    if not path:
        pytest.fail("Noto Sans Thai font not available in CI")
    return path


def test_real_ocr_thai_and_english_language_pack():
    languages = set(pytesseract.get_languages(config=""))
    assert {"tha", "eng"}.issubset(languages)

    image = Image.new("RGB", (1500, 220), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(_font_path(), 64)
    draw.text((30, 55), "SYNTHETIC OCR ภาษาไทย ทดสอบ", font=font, fill="black")

    result = ocr_region(
        image,
        (0, 0, 1500, 220),
        dpi=72,
        padding_pts=0,
        lang="tha+eng",
        upscale=1,
    )
    compact = "".join(result.text.split())
    assert "SYNTHETIC" in result.text.upper()
    assert any("\u0e00" <= ch <= "\u0e7f" for ch in compact)
    assert result.confidence > 0
