from datetime import datetime, timezone

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.extract.text import TextQuality
from pdf_document_intelligence.models.document import BoundingBox, FieldValue
from pdf_document_intelligence.validate.cross_validate import ThaiOcrCrossValidator

RELIABLE = TextQuality(printable_ratio=1.0, thai_valid_ratio=1.0, replacement_char_ratio=0.0, thai_combining_density=0.2, score=1.0, reliable=True)
UNRELIABLE = TextQuality(printable_ratio=1.0, thai_valid_ratio=1.0, replacement_char_ratio=0.0, thai_combining_density=0.0, score=0.85, reliable=False)


def _field(**overrides) -> FieldValue:
    base = dict(
        name="name",
        raw_value="มนบเบคกน",
        value="มนบเบคกน",
        type="string",
        bbox=BoundingBox(x=0, y=0, width=0, height=0, page=1),
        source="pdf_text",
        confidence=0.4,
        review_required=True,
    )
    base.update(overrides)
    return FieldValue(**base)


def test_skips_non_string_fields():
    v = ThaiOcrCrossValidator(pdf_path="unused.pdf", settings=Settings())
    field = _field(type="code")
    assert v.maybe_apply(field, UNRELIABLE) is field


def test_skips_non_thai_text():
    v = ThaiOcrCrossValidator(pdf_path="unused.pdf", settings=Settings())
    field = _field(raw_value="ABC123", value="ABC123")
    assert v.maybe_apply(field, UNRELIABLE) is field


def test_skips_when_page_text_layer_is_reliable():
    v = ThaiOcrCrossValidator(pdf_path="unused.pdf", settings=Settings())
    field = _field()
    assert v.maybe_apply(field, RELIABLE) is field


def test_skips_zero_area_bbox():
    v = ThaiOcrCrossValidator(pdf_path="unused.pdf", settings=Settings())
    field = _field(bbox=BoundingBox(x=0, y=0, width=0, height=0, page=1))
    assert v.maybe_apply(field, UNRELIABLE) is field
