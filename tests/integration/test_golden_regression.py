"""Golden regression test (proposal §45/§69): every pipeline change must be
checked against known-correct output for the real sample document before
it ships. Non-Thai fields (dn_no, do_no, order_no, line, pallet, lot,
article, barcode, weight/pu/sku qty) are diffed exactly against a
human-verified baseline — verified by cross-checking against the source
PDF's own per-department declared totals and spot-checking rows across
every department (see PR description).

Thai `name` fields are deliberately NOT diffed against exact expected
text: this specific sample's source PDF drops all Thai combining marks
(vowels/tone marks) from its text layer — a defect in the source file, not
this pipeline — so `name` values are known-unreliable pending OCR
(explicitly out of scope for this vertical slice). What IS regression-
tested is that `name` stays correctly flagged `review_required=True` with
the `TEXT_LAYER_UNRELIABLE` reason — i.e. that the pipeline keeps refusing
to silently trust that field, per "ไม่แน่ใจ = ห้ามเดา".
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
    mismatches = []
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            for field_name in NUMERIC_CODE_FIELDS:
                actual = row.fields[field_name].value
                exp = expected_row[field_name]
                if actual != exp:
                    mismatches.append((table.name, row.row_index, field_name, exp, actual))
    assert not mismatches, f"{len(mismatches)} field regressions: {mismatches[:10]}"


def test_thai_name_field_stays_flagged_for_review(result, expected):
    """Regression guard on the *safety* property, not the (currently
    unverifiable) text content: every name field must stay flagged
    review_required, and the reason must be the text-layer defect, not
    something silently swallowed."""
    for table, dept in zip(result.tables, expected["departments"]):
        for row, expected_row in zip(table.rows, dept["rows"]):
            name_field = row.fields["name"]
            assert name_field.review_required == expected_row["name_review_required"]
            if expected_row["name_review_required"]:
                assert "TEXT_LAYER_UNRELIABLE" in name_field.validation_flags


def test_document_status_is_never_silently_auto_approved(result):
    """Given the known text-layer defect, this document must never come out
    AUTO_APPROVED — that would mean the pipeline stopped noticing it."""
    assert result.status != "AUTO_APPROVED"
