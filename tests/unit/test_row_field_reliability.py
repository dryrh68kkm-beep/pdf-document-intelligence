from pdf_document_intelligence.catalog.apply import apply_catalog_to_row
from pdf_document_intelligence.catalog.loader import CatalogEntry
from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.extract.text import TextQuality
from pdf_document_intelligence.models.document import BoundingBox, FieldValue, TableRow
from pdf_document_intelligence.tables.fields import _parse_field


def _quality() -> TextQuality:
    return TextQuality(printable_ratio=1.0, thai_valid_ratio=1.0, replacement_char_ratio=0.0, thai_combining_density=-1.0, score=1.0, reliable=True)


def _bbox() -> BoundingBox:
    return BoundingBox(x=1, y=1, width=10, height=10, page=1)


def test_invalid_article_format_requires_review():
    field = _parse_field("article", "code", "12345ABC", _bbox(), _quality(), Settings())
    assert field.review_required is True
    assert "INVALID_ARTICLE_FORMAT" in field.validation_flags
    assert field.confidence <= 0.25


def test_valid_article_format_remains_high_confidence():
    field = _parse_field("article", "code", "1234567-89-012", _bbox(), _quality(), Settings())
    assert field.review_required is False


def test_invalid_barcode_format_requires_review():
    field = _parse_field("barcode", "code", "ABC885000", _bbox(), _quality(), Settings())
    assert field.review_required is True
    assert "INVALID_BARCODE_FORMAT" in field.validation_flags


def test_valid_internal_barcode_is_accepted():
    field = _parse_field("barcode", "code", "1234567", _bbox(), _quality(), Settings())
    assert field.review_required is False


def _field(name: str, value: str) -> FieldValue:
    return FieldValue(name=name, raw_value=value, value=value, type="string" if name == "name" else "code", bbox=_bbox(), source="pdf_text", confidence=0.99)


def _catalog_entry(name: str) -> CatalogEntry:
    return CatalogEntry(barcode="8850000000001", name=name, structure="", root_code="")


def test_catalog_name_mismatch_is_audit_only():
    row = TableRow(row_index=1, fields={"barcode": _field("barcode", "8850000000001"), "name": _field("name", "SOURCE NAME")}, confidence_band="HIGH")
    updated = apply_catalog_to_row(row, {"8850000000001": _catalog_entry("MASTER NAME")})
    name = updated.fields["name"]
    assert name.value == "MASTER NAME"
    assert name.raw_value == "SOURCE NAME"
    assert name.review_required is False
    assert name.confidence == 1.0
    assert "CATALOG_NAME_MISMATCH" in name.validation_flags
    assert "CATALOG_MATCH" in name.validation_flags


def test_catalog_exact_name_match_does_not_require_review():
    row = TableRow(row_index=1, fields={"barcode": _field("barcode", "8850000000001"), "name": _field("name", "MASTER NAME")}, confidence_band="HIGH")
    updated = apply_catalog_to_row(row, {"8850000000001": _catalog_entry("MASTER NAME")})
    name = updated.fields["name"]
    assert name.review_required is False
    assert name.validation_flags == ["CATALOG_MATCH"]
