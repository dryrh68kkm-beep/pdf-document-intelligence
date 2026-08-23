from datetime import datetime, timezone
from unittest.mock import patch

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.extract.ocr import OCRResult
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


def test_runs_ocr_when_page_reliable_but_field_itself_shows_encoding_defect():
    """Regression guard for the garbled-name bug: a corrupted PDF font can
    scramble a handful of product-name cells (e.g. "เพอร์ริเย่ต์" becomes
    "เพอรรรต่ นตนตแร") while the rest of the page (numbers, headers, other
    names) stays clean enough that the page-level average is still scored
    "reliable" - so OCR must still run when the *specific field's* own text
    shows the reordering defect, not only when the whole page fails."""
    v = ThaiOcrCrossValidator(pdf_path="unused.pdf", settings=Settings())
    garbled = "เพอรรรต่ นตนตแร ่1500 มล.แพซค 6"
    field = _field(raw_value=garbled, value=garbled, bbox=BoundingBox(x=0, y=0, width=10, height=10, page=1))
    ocr_result = OCRResult(text="เพอร์ร่า น้าแร่ 1500 มล.แพ็ค 6", confidence=0.93)
    with patch("pdf_document_intelligence.validate.cross_validate.render_page", return_value=None), \
         patch("pdf_document_intelligence.validate.cross_validate.ocr_region", return_value=ocr_result):
        updated = v.maybe_apply(field, RELIABLE)
    assert updated.source == "ocr"
    assert updated.value == "เพอร์ร่า น้าแร่ 1500 มล.แพ็ค 6"
    assert updated.review_required is True


def test_high_confidence_ocr_still_stays_review_required():
    """Regression guard (L1-002): a page already flagged text-layer-
    unreliable is why OCR runs at all - tesseract's own confidence score
    measures glyph-recognition certainty, not semantic correctness, so a
    "confident" OCR misread must still surface for human review. Must
    hold even when the OCR text doesn't conflict with the (already
    known-unreliable) PDF text layer."""
    v = ThaiOcrCrossValidator(pdf_path="unused.pdf", settings=Settings())
    field = _field(bbox=BoundingBox(x=0, y=0, width=10, height=10, page=1))
    high_confidence_result = OCRResult(text="มินิเค้กแฟนซี", confidence=0.99)
    with patch("pdf_document_intelligence.validate.cross_validate.render_page", return_value=None), \
         patch("pdf_document_intelligence.validate.cross_validate.ocr_region", return_value=high_confidence_result):
        updated = v.maybe_apply(field, UNRELIABLE)
    assert updated.confidence == 0.99
    assert updated.review_required is True
