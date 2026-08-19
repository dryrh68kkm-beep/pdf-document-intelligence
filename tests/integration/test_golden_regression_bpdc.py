"""Golden regression test for the packing_list_bpdc template (proposal
§45/§69, same pattern as test_golden_regression.py for packing_list_bigc).

This document ("BPDC") is a structurally different layout confirmed by the
user as the primary/most-common document type going forward: "Department"
is an inline, forward-filled table column instead of a per-page heading,
and rows are grouped into pallet blocks (by a "Pallet no. : X  Lot no. : Y"
line) that can span multiple pages and multiple departments — see
templates/packing_list_bpdc.py and tables/reconstruct_bpdc.py.

The orchestrator regroups parsed rows by department after pallet-block
reconstruction so the downstream table shape (list of department tables)
matches packing_list_bigc's for the API/SPA layer — this test asserts that
regrouping is stable and reconciliation still runs correctly per pallet
block (not per department, since only the pallet-level Total is printed).

Same evidence/traceability rules as the BIGC golden test apply: `name` is
diffed exactly only for catalog-sourced rows (ground truth); numeric/code
fields must never be touched by OCR or catalog lookup.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_document_intelligence.pipeline.orchestrator import process_document

GOLDEN_DIR = Path(__file__).parent.parent / "golden"
SAMPLE = GOLDEN_DIR / "samples" / "BPDC_91101_190826.pdf"
EXPECTED = GOLDEN_DIR / "expected" / "BPDC_91101_190826.json"

NUMERIC_CODE_FIELDS = (
    "dn_no", "do_no", "order_no", "line",
    "article", "barcode", "weight_qty", "pu_qty", "sku_qty",
)

# This document's text layer is reliable (unlike the BIGC sample's known
# ToUnicode CMap defect), so the catalog + OCR resolution floors can be set
# tighter to the observed 96.6% catalog match rate.
MIN_CATALOG_MATCH_RATE = 0.90
MIN_TOTAL_RESOLUTION_RATE = 0.95


@pytest.fixture(scope="module")
def result():
    return process_document(SAMPLE)


@pytest.fixture(scope="module")
def expected():
    return json.loads(EXPECTED.read_text(encoding="utf-8"))


def test_template_detected_as_bpdc(result):
    assert result.document_type == "packing_list_bpdc"


def test_document_reconciles_with_zero_errors(result, expected):
    assert result.validation.reconciled is expected["reconciled"]
    assert len(result.validation.errors) == expected["validation_errors"]


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


def test_unresolved_names_stay_flagged_for_review(result, expected):
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            name_field = row.fields["name"]
            assert name_field.review_required == expected_row["name_review_required"]
            assert name_field.raw_value
            if name_field.source in ("ocr", "cross_validated"):
                assert name_field.ocr_raw_value
                assert name_field.ocr_confidence is not None


def test_non_product_classification_matches_baseline(result, expected):
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            assert row.suspected_non_product == expected_row["suspected_non_product"]


def test_catalog_match_is_exact_ground_truth(result):
    """Spot-check a specific known-correct catalog resolution (verified by
    hand against the source PDF and the catalog CSV) - guards against a
    catalog-loading or lookup-key regression silently producing wrong (but
    still 'confident') values."""
    beverage = next(t for t in result.tables if t.name == "BEVERAGE")
    row1 = beverage.rows[0]
    assert row1.fields["barcode"].value == "8854641002822"
    assert row1.fields["name"].value == "HPP น้ำดื่ม  1500 มล."
    assert row1.fields["name"].source == "master_catalog"


def test_no_non_product_rows_in_this_sample(result):
    """This BPDC sample has no PAQ-prefixed marketing-material rows or
    "ของแถม" giveaway lines, so the conservative classifier should flag
    zero — a nonzero count here would mean either a regression (classifier
    started matching real products) or a genuinely new case worth a
    human's eyes either way."""
    flagged = [row for table in result.tables for row in table.rows if row.suspected_non_product]
    assert flagged == []


def test_row_index_renumbered_sequentially_per_department(result):
    """Rows are collected from pallet blocks (which can carry several
    departments) and regrouped by department — row_index must come out
    1..N per department table, not the original pallet-block position."""
    for table in result.tables:
        assert [row.row_index for row in table.rows] == list(range(1, len(table.rows) + 1))
