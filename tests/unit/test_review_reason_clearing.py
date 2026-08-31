"""User report: a row a human already corrected in the Review UI kept
showing up in Review anyway. Root cause -
api/review.py's _recompute_review_flags() only ever re-derived
AMOUNT_MISMATCH and MISSING_DEPARTMENT from the post-correction row; every
other reason the pipeline could attach (OCR_LOW_CONFIDENCE,
TEXT_LAYER_UNRELIABLE, COLUMN_OVERFLOW_SPLIT, SOURCE_CONFLICT,
CATALOG_NAME_MISMATCH, MISSING_FIELD, TYPE_PARSE_FAILED,
INVALID_ARTICLE_FORMAT, INVALID_BARCODE_FORMAT) was carried over verbatim
from before the edit forever, no matter what got corrected.

Fixed by (1) unconditionally dropping the "extraction trust" reasons -
they describe the pipeline's confidence in its own OCR, not a fact about
the row's current data, so a human typing a value already supersedes them,
matching confirm_review_row's own "safe to clear with one click" set a few
lines below in the same file - and (2) properly re-deriving
MISSING_FIELD/TYPE_PARSE_FAILED (checked against every required column,
not just the one just edited, so fixing one required field never hides a
different one that's still genuinely empty) and INVALID_ARTICLE_FORMAT/
INVALID_BARCODE_FORMAT (re-validated against the corrected value's actual
format, not blindly cleared)."""
from __future__ import annotations

import json

from pdf_document_intelligence.api.review import apply_correction
from pdf_document_intelligence.db.connection import open_independent_connection
from pdf_document_intelligence.db.repository import Repository
from pdf_document_intelligence.models.document import BoundingBox, FieldValue, TableRow
from tests.unit.db_helpers import make_result


def _fv(name, value, *, review=False, flags=None):
    return FieldValue(
        name=name, raw_value=str(value) if value is not None else "", value=value, type="string",
        bbox=BoundingBox(x=0, y=0, width=1, height=1, page=1), source="pdf_text",
        confidence=0.4, validation_flags=flags or [], review_required=review,
    )


def _row_with_flags(*, barcode="8850000000001", article="12345678-00-001", name="สินค้า A",
                     weight_qty=10.0, pu_qty=5, sku_qty=5, flag_field="name", flags=None):
    fields = {
        "barcode": _fv("barcode", barcode),
        "article": _fv("article", article),
        "name": _fv("name", name),
        "weight_qty": _fv("weight_qty", weight_qty),
        "pu_qty": _fv("pu_qty", pu_qty),
        "sku_qty": _fv("sku_qty", sku_qty),
    }
    fields[flag_field] = _fv(flag_field, fields[flag_field].value, review=True, flags=flags or [])
    return TableRow(row_index=0, fields=fields, confidence_band="LOW")


def _seed(repo: Repository, row: TableRow, doc_id="doc-1"):
    repo.create_document(doc_id, sha256="abc123", filename="test.pdf", file_size=100)
    result = make_result(doc_id, "test.pdf", [("BAKERY", [row])])
    repo.set_document_complete(doc_id, 1, {"confidence": 0.7, "statusDocument": "MANUAL_REVIEW", "reconciled": True})
    from pdf_document_intelligence.api.rows import persist_document_result
    persist_document_result(doc_id, result, repo)
    return repo.list_product_rows()[0]


def _repo(tmp_path):
    return Repository(open_independent_connection(tmp_path / "app.db"))


def test_correcting_any_field_clears_ocr_low_confidence(tmp_path):
    repo = _repo(tmp_path)
    row = _seed(repo, _row_with_flags(flag_field="name", flags=["OCR_LOW_CONFIDENCE"]))
    assert row["review_required"] == 1

    apply_correction(repo, row["id"], "weight_qty", 12.0, reason="ตรวจจากเอกสารต้นฉบับ")

    reloaded = repo.get_product_row(row["id"])
    assert "OCR_LOW_CONFIDENCE" not in json.loads(reloaded["review_reasons"])
    assert not reloaded["review_required"]


def test_correcting_any_field_clears_text_layer_unreliable_and_column_overflow(tmp_path):
    repo = _repo(tmp_path)
    row = _seed(repo, _row_with_flags(flag_field="name", flags=["TEXT_LAYER_UNRELIABLE", "COLUMN_OVERFLOW_SPLIT"]))

    apply_correction(repo, row["id"], "sku_qty", 6, reason="ตรวจจากเอกสารต้นฉบับ")

    reloaded = repo.get_product_row(row["id"])
    reasons = json.loads(reloaded["review_reasons"])
    assert "TEXT_LAYER_UNRELIABLE" not in reasons
    assert "COLUMN_OVERFLOW_SPLIT" not in reasons
    assert not reloaded["review_required"]


def test_correcting_article_to_a_valid_format_clears_invalid_article_format(tmp_path):
    repo = _repo(tmp_path)
    row = _seed(repo, _row_with_flags(article="BADCODE", flag_field="article", flags=["INVALID_ARTICLE_FORMAT"]))

    apply_correction(repo, row["id"], "article", "12345678-00-001", reason="ตรวจจากเอกสารต้นฉบับ")

    reloaded = repo.get_product_row(row["id"])
    assert "INVALID_ARTICLE_FORMAT" not in json.loads(reloaded["review_reasons"])
    assert not reloaded["review_required"]


def test_correcting_article_to_still_invalid_format_keeps_the_flag(tmp_path):
    """A bad correction must not silently disappear from Review - only a
    genuinely valid value clears INVALID_ARTICLE_FORMAT."""
    repo = _repo(tmp_path)
    row = _seed(repo, _row_with_flags(article="BADCODE", flag_field="article", flags=["INVALID_ARTICLE_FORMAT"]))

    apply_correction(repo, row["id"], "article", "STILL-NOT-VALID", reason="test")

    reloaded = repo.get_product_row(row["id"])
    assert "INVALID_ARTICLE_FORMAT" in json.loads(reloaded["review_reasons"])
    assert reloaded["review_required"]


def test_correcting_barcode_to_a_valid_format_clears_invalid_barcode_format(tmp_path):
    repo = _repo(tmp_path)
    row = _seed(repo, _row_with_flags(barcode="BAD", flag_field="barcode", flags=["INVALID_BARCODE_FORMAT"]))

    apply_correction(repo, row["id"], "barcode", "8850000009999", reason="ตรวจจากเอกสารต้นฉบับ")

    reloaded = repo.get_product_row(row["id"])
    assert "INVALID_BARCODE_FORMAT" not in json.loads(reloaded["review_reasons"])
    assert not reloaded["review_required"]


def test_correcting_one_missing_field_does_not_hide_a_still_missing_one(tmp_path):
    """MISSING_FIELD is a single flattened flag - fixing weight_qty must not
    make sku_qty's own emptiness invisible."""
    repo = _repo(tmp_path)
    row = _seed(repo, _row_with_flags(weight_qty=None, sku_qty=None, flag_field="weight_qty", flags=["MISSING_FIELD"]))

    apply_correction(repo, row["id"], "weight_qty", 10.0, reason="ตรวจจากเอกสารต้นฉบับ")

    reloaded = repo.get_product_row(row["id"])
    assert reloaded["sku_qty"] is None
    assert "MISSING_FIELD" in json.loads(reloaded["review_reasons"])
    assert reloaded["review_required"]


def test_correcting_the_last_missing_field_clears_missing_field(tmp_path):
    repo = _repo(tmp_path)
    row = _seed(repo, _row_with_flags(sku_qty=None, flag_field="sku_qty", flags=["MISSING_FIELD"]))

    apply_correction(repo, row["id"], "sku_qty", 6, reason="ตรวจจากเอกสารต้นฉบับ")

    reloaded = repo.get_product_row(row["id"])
    assert "MISSING_FIELD" not in json.loads(reloaded["review_reasons"])
    assert not reloaded["review_required"]


def test_amount_mismatch_still_blocks_review_clearing_even_after_an_unrelated_correction(tmp_path):
    """A real remaining problem (AMOUNT_MISMATCH) must keep the row in
    Review even though the extraction-trust flag it also carried gets
    cleared by the same correction."""
    repo = _repo(tmp_path)
    row = _seed(repo, _row_with_flags(flag_field="name", flags=["OCR_LOW_CONFIDENCE"]))
    apply_correction(repo, row["id"], "unit_price", 10.0, reason="test")
    apply_correction(repo, row["id"], "amount", 999.0, reason="test")

    mismatched = repo.get_product_row(row["id"])
    assert "AMOUNT_MISMATCH" in json.loads(mismatched["review_reasons"])
    assert "OCR_LOW_CONFIDENCE" not in json.loads(mismatched["review_reasons"])
    assert mismatched["review_required"]
