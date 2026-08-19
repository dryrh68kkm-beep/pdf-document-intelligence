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
fix can recover them. Two independent recovery paths run, in priority
order:

1. Master catalog lookup by barcode (catalog/) — ground truth (an exact
   match against real master data), so a hit is never flagged for review.
2. Region-level Tesseract OCR (tha+eng) of the rendered page, for rows the
   catalog doesn't cover — genuinely uncertain, so it stays
   review_required even when it recovers legible text.

`name` is never diffed against exact expected text for the OCR-only
remainder (mixed Thai/English SKU-prefix text isn't reliably OCR'd), but
IS diffed exactly for catalog-sourced rows, since those are ground truth.
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

# Below this fraction of `name` fields resolved (catalog match or OCR),
# something in the recovery pipeline (catalog path, rendering DPI, crop
# padding, tesseract lang data) has regressed.
MIN_CATALOG_MATCH_RATE = 0.80
MIN_TOTAL_RESOLUTION_RATE = 0.90


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
    """Neither OCR nor the catalog lookup may ever touch code/numeric
    fields — only `name`."""
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
                    "OCR/catalog must not touch non-Thai fields"
                )
    assert not mismatches, f"{len(mismatches)} field regressions: {mismatches[:10]}"


def test_catalog_lookup_resolves_most_names_as_ground_truth(result, expected):
    """Regression guard on the primary fix: most `name` fields should
    resolve to an exact master-catalog match (never flagged for review),
    with OCR as the fallback for the remainder - and both sources'
    assignment must be deterministic (matches the committed baseline)."""
    catalog_matched = 0
    resolved = 0
    total = 0
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            total += 1
            source = row.fields["name"].source
            assert source == expected_row["name_source"], (
                f"{table.name} row {row.row_index}: name source drifted from baseline "
                f"({expected_row['name_source']} -> {source})"
            )
            if source == "master_catalog":
                catalog_matched += 1
                assert row.fields["name"].review_required is False, "a catalog match must never need review"
            if source in ("master_catalog", "ocr", "cross_validated"):
                resolved += 1

    catalog_rate = catalog_matched / total
    resolution_rate = resolved / total
    assert catalog_rate >= MIN_CATALOG_MATCH_RATE, f"catalog match rate {catalog_rate:.1%} below {MIN_CATALOG_MATCH_RATE:.0%} floor"
    assert resolution_rate >= MIN_TOTAL_RESOLUTION_RATE, f"total resolution rate {resolution_rate:.1%} below {MIN_TOTAL_RESOLUTION_RATE:.0%} floor"


def test_catalog_match_is_exact_ground_truth(result):
    """Spot-check specific known-correct catalog resolutions (verified by
    hand against the source PDF and the catalog CSV) - guards against a
    catalog-loading or lookup-key regression silently producing wrong
    (but still 'confident') values."""
    bakery = next(t for t in result.tables if t.name == "BAKERY")
    row1 = bakery.rows[0]
    assert row1.fields["barcode"].value == "8851886009821"
    assert row1.fields["name"].value == "มินิเค้กแฟนซี"
    assert row1.fields["name"].source == "master_catalog"


def test_unresolved_names_stay_flagged_for_review(result, expected):
    """Regression guard on the *safety* property for whatever the catalog
    doesn't cover: OCR results (or a bare PDF fallback) never get silently
    trusted - every non-catalog name stays review_required, and every
    field carries both raw PDF and raw OCR text (when OCR ran) for a human
    to compare, never a single opaque 'corrected' string with no evidence
    trail."""
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            name_field = row.fields["name"]
            assert name_field.review_required == expected_row["name_review_required"]
            assert name_field.raw_value  # original PDF-text reading always preserved
            if name_field.source in ("ocr", "cross_validated"):
                assert name_field.ocr_raw_value
                assert name_field.ocr_confidence is not None


def test_non_product_classification_matches_baseline(result, expected):
    """This document has no internal marketing-material/giveaway rows, so
    the conservative classifier should flag zero - a nonzero count would
    mean the classifier started matching real products (regression) or a
    genuinely new case appeared that needs eyes on it either way."""
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            assert row.suspected_non_product == expected_row["suspected_non_product"]


def test_document_status_is_never_silently_auto_approved(result):
    """Given the known text-layer defect, this document must never come out
    AUTO_APPROVED — that would mean the pipeline stopped noticing it."""
    assert result.status != "AUTO_APPROVED"
