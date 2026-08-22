from pdf_document_intelligence.models.document import BoundingBox, ExtractedTable, FieldValue, TableRow, ValidationIssue, ValidationSummary
from pdf_document_intelligence.quality.score import score_quality


def _field(name: str, value, *, confidence: float = 1.0, source: str = "pdf_text", flags=None, review=False):
    return FieldValue(
        name=name,
        raw_value=str(value or ""),
        value=value,
        type="code" if name in {"article", "barcode"} else "string",
        bbox=BoundingBox(x=0, y=0, width=1, height=1, page=1),
        source=source,
        confidence=confidence,
        validation_flags=flags or [],
        review_required=review,
    )


def _table(rows):
    return [ExtractedTable(name="TEST", page_start=1, page_end=1, header=[], rows=rows, source_pages=[1])]


def test_quality_score_verified_for_clean_master_matched_rows():
    row = TableRow(
        row_index=1,
        confidence_band="HIGH",
        fields={
            "article": _field("article", "1234567-89-012"),
            "barcode": _field("barcode", "8850000000001"),
            "name": _field("name", "MASTER", source="master_catalog"),
        },
    )
    result = score_quality(_table([row]), ValidationSummary(reconciled=True))
    assert result.score == 100.0
    assert result.band == "VERIFIED"
    assert result.verified_rows == 1
    assert result.review_rows == 0


def test_quality_score_drops_for_invalid_identity_and_review_row():
    row = TableRow(
        row_index=1,
        confidence_band="LOW",
        fields={
            "article": _field("article", "BAD", confidence=0.2, flags=["INVALID_ARTICLE_FORMAT"], review=True),
            "barcode": _field("barcode", "ABC", confidence=0.2, flags=["INVALID_BARCODE_FORMAT"], review=True),
            "name": _field("name", "RAW", confidence=0.5),
        },
    )
    validation = ValidationSummary(
        reconciled=False,
        errors=[ValidationIssue(code="PAGE_DATA_MISSING", message="missing", severity="error")],
    )
    result = score_quality(_table([row]), validation)
    assert result.band in {"NEED_REVIEW", "HIGH_RISK"}
    assert result.review_rows == 1
    assert result.error_count == 1
    assert result.breakdown["identity"] == 0.0


def test_quality_score_empty_document_is_high_risk():
    result = score_quality([], ValidationSummary(reconciled=False))
    assert result.score == 0.0
    assert result.band == "HIGH_RISK"
    assert result.row_count == 0
