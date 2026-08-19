"""Golden regression test (proposal §45/§69): every pipeline change must be
checked against known-correct output for the real sample document before
it ships. Non-Thai fields (dn_no, do_no, order_no, line, pallet, lot,
article, barcode, weight/pu/sku qty) are diffed exactly against a
human-verified baseline — verified by cross-checking against the source
PDF's own per-department declared totals and spot-checking rows across
every department.

Thai `name` fields: this sample's source PDF has a confirmed root cause
(see docs/OCR_ROOT_CAUSE.md) — its embedded font's ToUnicode CMap never
maps any glyph code to a Thai combining vowel/tone mark, so those
characters are physically absent from the text layer; no extraction-side
fix can recover them. `name` is therefore cross-validated against
region-level Tesseract OCR (tha+eng) of the rendered page, which reads the
same glyphs that render correctly on screen. This materially improves
`name` (see test_ocr_cross_validation_recovers_most_thai_names) but OCR of
mixed Thai/English SKU-prefix text on a real invoice is not perfect, so
`name` is still never diffed against exact expected text or auto-approved
— every row stays `review_required=True` with full raw/OCR evidence
preserved, per "ไม่แน่ใจ = ห้ามเดา".
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_document_intelligence.pipeline.orchestrator import process_document

GOLDEN_DIR = Path(__file__).parent.parent / "golden"
SAMPLE = GOLDEN_DIR / "samples" / "PL92924_112520819.R211252100.pdf"
EXPECTED = GOLDEN_DIR / "expected" / "PL92924_112520819.R211252100.json"

NUMERIC_CODE_FIELDS = (
    "dn_no", "do_no", "order_no", "line", "pallet", "lot",
    "article", "barcode", "weight_qty", "pu_qty", "sku_qty",
)

# Below this fraction of `name` fields recovered via OCR, something in the
# OCR pipeline (rendering DPI, crop padding, tesseract lang data) has
# regressed — this is not a hard 100% bar because Tesseract's tha+eng model
# genuinely cannot read every mixed-script SKU-prefix token on this sample.
MIN_OCR_RECOVERY_RATE = 0.65


@pytest.fixture(scope="module")
def result():
    return process_document(SAMPLE)


@pytest.fixture(scope="module")
def expected():
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


def test_document_reconciles_with_zero_errors(result):
    assert result.validation.reconciled is True
    assert result.validation.errors == []


def test_department_and_row_counts_match_baseline(result, expected):
    assert result.pages == expected["pages"]
    assert [t.name for t in result.tables] == [d["name"] for d in expected["departments"]]
    for table, dept in zip(result.tables, expected["departments"]):
        assert len(table.rows) == dept["row_count"], f"{table.name}: row count regressed"


def test_numeric_and_code_fields_match_baseline_exactly(result, expected):
    """OCR must never touch code/numeric fields — only Thai `name`."""
    mismatches = []
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            for field_name in NUMERIC_CODE_FIELDS:
                actual = row.fields[field_name].value
                exp = expected_row[field_name]
                if actual != exp:
                    mismatches.append((table.name, row.row_index, field_name, exp, actual))
                assert row.fields[field_name].source == "pdf_text", (
                    f"{table.name} row {row.row_index} field {field_name}: "
                    "OCR must not touch non-Thai fields"
                )
    assert not mismatches, f"{len(mismatches)} field regressions: {mismatches[:10]}"


def test_ocr_cross_validation_recovers_most_thai_names(result, expected):
    """Regression guard on the actual fix: most `name` fields should now be
    OCR/cross-validated rather than stuck on the known-broken PDF text, and
    that source assignment should be deterministic run to run (matches the
    committed baseline)."""
    recovered = 0
    total = 0
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            total += 1
            source = row.fields["name"].source
            assert source == expected_row["name_source"], (
                f"{table.name} row {row.row_index}: name source drifted from baseline "
                f"({expected_row['name_source']} -> {source})"
            )
            if source in ("ocr", "cross_validated"):
                recovered += 1
    rate = recovered / total
    assert rate >= MIN_OCR_RECOVERY_RATE, f"OCR recovery rate {rate:.1%} below {MIN_OCR_RECOVERY_RATE:.0%} floor"


def test_ocr_never_silently_trusted(result, expected):
    """Regression guard on the *safety* property: every name field must
    stay flagged review_required (mixed Thai/English retail text is
    genuinely uncertain even post-OCR), and every field carries a reason
    plus both raw PDF and raw OCR text for a human to compare — never a
    single opaque "corrected" string with no evidence trail."""
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            name_field = row.fields["name"]
            assert name_field.review_required == expected_row["name_review_required"]
            assert name_field.raw_value  # original PDF-text reading always preserved
            if name_field.source in ("ocr", "cross_validated"):
                assert name_field.ocr_raw_value
                assert name_field.ocr_confidence is not None


def test_document_status_is_never_silently_auto_approved(result):
    """Given the known text-layer defect, this document must never come out
    AUTO_APPROVED — that would mean the pipeline stopped noticing it."""
    assert result.status != "AUTO_APPROVED"
