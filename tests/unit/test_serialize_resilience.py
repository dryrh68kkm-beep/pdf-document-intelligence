"""Live reports (browser Console): GET /api/products and GET /api/documents
500ing - a much wider blast radius than the Division-summary crashes fixed
earlier (see test_division_summary_resilience.py), because these two
endpoints serialize every product row / every document in the whole app in
one list comprehension, not one document at a time. One row's corrupted
stored JSON used to take every other document's data down with it.

Exercises serialize.py's pure functions directly with hand-built dicts (no
DB needed) - fast and deterministic.
"""
from __future__ import annotations

from pdf_document_intelligence.api.serialize import document_summary_json, product_row_json


def _row(**overrides) -> dict:
    base = {
        "id": "row-1",
        "document_id": "doc-1",
        "department": "BAKERY",
        "source_page": 1,
        "confidence_band": "HIGH",
        "review_required": 0,
        "review_reasons": None,
        "resolution_status": "OCR",
        "suspected_non_product": 0,
        "non_product_reasons": None,
        "fields_json": '{"barcode": {"value": "8850000000001"}}',
        "updated_at": "2026-01-01T00:00:00+00:00",
        "barcode": "8850000000001",
    }
    base.update(overrides)
    return base


def _doc(**overrides) -> dict:
    base = {
        "id": "doc-1",
        "filename": "doc1.pdf",
        "status": "complete",
        "uploaded_at": "2026-01-01T00:00:00+00:00",
        "progress_stage": "done",
        "progress_current": 1,
        "progress_total": 1,
        "error": None,
        "page_count": 1,
        "meta_json": None,
    }
    base.update(overrides)
    return base


def test_product_row_json_tolerates_corrupted_fields_json():
    row = _row(fields_json="{not valid json")
    result = product_row_json(row, "doc1.pdf")
    assert result["fields"] == {}


def test_product_row_json_tolerates_fields_json_not_an_object():
    row = _row(fields_json="null")
    result = product_row_json(row, "doc1.pdf")
    assert result["fields"] == {}


def test_product_row_json_tolerates_review_reasons_not_a_list():
    row = _row(review_reasons='"just a string"')
    result = product_row_json(row, "doc1.pdf")
    assert result["reviewReasons"] == []


def test_product_row_json_tolerates_non_product_reasons_corrupted_json():
    row = _row(non_product_reasons="{not valid json")
    result = product_row_json(row, "doc1.pdf")
    assert result["nonProductReasons"] == []


def test_field_json_tolerates_bbox_not_a_dict():
    row = _row(fields_json='{"barcode": {"value": "x", "bbox": ["not", "a", "dict"]}}')
    result = product_row_json(row, "doc1.pdf")
    assert result["fields"]["barcode"]["page"] is None
    assert result["fields"]["barcode"]["bbox"] == ["not", "a", "dict"]


def test_field_json_tolerates_non_numeric_confidence():
    row = _row(fields_json='{"barcode": {"value": "x", "confidence": "high"}}')
    result = product_row_json(row, "doc1.pdf")
    assert result["fields"]["barcode"]["confidence"] is None


def test_document_summary_json_tolerates_meta_json_not_an_object():
    doc = _doc(meta_json="null")
    summary = document_summary_json(doc)
    assert summary["errors"] == 0
    assert summary["confidence"] is None


def test_document_summary_json_tolerates_validation_issues_not_a_list():
    import json

    doc = _doc(meta_json=json.dumps({"validationIssues": "not-a-list"}))
    summary = document_summary_json(doc)
    assert summary["errors"] == 0
    assert summary["warnings"] == 0


def test_document_summary_json_tolerates_validation_issue_missing_severity():
    """The original bug: i["severity"] (bracket access) raised KeyError for
    an issue dict with no "severity" key at all - unlike divisions.py's
    equivalent, this path used i["severity"] rather than i.get("severity")."""
    import json

    doc = _doc(meta_json=json.dumps({"validationIssues": [{"message": "no severity field here"}]}))
    summary = document_summary_json(doc)
    assert summary["errors"] == 0
    assert summary["warnings"] == 0


def test_document_summary_json_tolerates_validation_issues_with_non_dict_items():
    import json

    doc = _doc(meta_json=json.dumps({"validationIssues": ["oops", 5, None]}))
    summary = document_summary_json(doc)
    assert summary["errors"] == 0
    assert summary["warnings"] == 0


def test_document_summary_json_tolerates_non_numeric_confidence():
    import json

    doc = _doc(meta_json=json.dumps({"confidence": "high"}))
    summary = document_summary_json(doc)
    assert summary["confidence"] is None


def test_document_summary_json_tolerates_quality_not_a_dict():
    import json

    doc = _doc(meta_json=json.dumps({"quality": "not-a-dict"}))
    summary = document_summary_json(doc)
    assert summary["qualityScore"] is None
