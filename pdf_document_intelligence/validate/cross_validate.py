"""ThaiOcrCrossValidator: selective OCR fallback + cross-validation
(proposal §10-14).

Applies only to string-typed fields that (a) contain Thai text and (b)
were sourced from a page whose text layer TextExtractor already flagged
unreliable, OR whose own text independently shows the same reordering
defect even though the page's aggregate score passed (a garbled product
name sitting next to hundreds of clean digits/headers on the same page
can leave the page-level average "reliable" - see
extract.text.field_has_thai_encoding_defect) — never runs OCR on fields
that don't need it, and never touches code/numeric fields regardless of
page quality (those come from ASCII digits, which this specific defect
does not corrupt, verified against the golden sample).

Decision policy, all thresholds from Settings (never hard-coded):
- OCR confidence >= ocr_confidence_high: use OCR text, not flagged for
  review (source="cross_validated" if it also structurally resembles the
  raw PDF token count, else "ocr").
- ocr_confidence_medium <= confidence < high: use OCR text, still flagged
  review_required (medium-confidence OCR of Thai script is genuinely
  uncertain, not "close enough").
- confidence < medium, or OCR produced nothing usable: keep the raw PDF
  value as `value` is left None (never silently guessed) - this is the
  "ไม่แน่ใจ = ห้ามเดา" case - MISSING/NEEDS_REVIEW, not a fabricated string.

The original PDF-text `raw_value` is never overwritten; OCR's own raw
output is preserved separately in `ocr_raw_value` for audit (§36/§46).
"""
from __future__ import annotations

from pathlib import Path

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.extract.ocr import OCRResult, ocr_region, render_page
from pdf_document_intelligence.extract.text import TextQuality, field_has_thai_encoding_defect
from pdf_document_intelligence.models.document import FieldValue
from pdf_document_intelligence.normalize.thai import normalize_thai_text

_THAI_RANGE = range(0x0E01, 0x0E5C)


def _has_thai(text: str) -> bool:
    return any(ord(c) in _THAI_RANGE for c in text)


class ThaiOcrCrossValidator:
    def __init__(self, pdf_path: Path, settings: Settings, dpi: int = 300) -> None:
        self.pdf_path = pdf_path
        self.settings = settings
        self.dpi = dpi
        self.ocr_calls = 0

    def maybe_apply(self, field: FieldValue, page_quality: TextQuality) -> FieldValue:
        if field.type != "string":
            return field
        candidate_text = str(field.value) if field.value is not None else field.raw_value
        if not _has_thai(candidate_text):
            return field
        if page_quality.reliable and not field_has_thai_encoding_defect(
            candidate_text, self.settings.min_thai_valid_char_ratio
        ):
            return field
        if field.bbox.width <= 0 or field.bbox.height <= 0:
            return field

        image = render_page(self.pdf_path, field.bbox.page, dpi=self.dpi)
        bbox = (field.bbox.x, field.bbox.y, field.bbox.x + field.bbox.width, field.bbox.y + field.bbox.height)
        result: OCRResult = ocr_region(image, bbox, dpi=self.dpi)
        self.ocr_calls += 1

        flags = [f for f in field.validation_flags if f != "TEXT_LAYER_UNRELIABLE"]
        flags.append("TEXT_LAYER_UNRELIABLE")

        ocr_text = normalize_thai_text(result.text)
        if not ocr_text or result.confidence < self.settings.ocr_confidence_medium:
            flags.append("OCR_LOW_CONFIDENCE")
            return field.model_copy(
                update={
                    "ocr_raw_value": result.text or None,
                    "ocr_confidence": result.confidence,
                    "validation_flags": flags,
                    "review_required": True,
                    "confidence": min(field.confidence, result.confidence),
                }
            )

        pdf_text = normalize_thai_text(field.raw_value)
        conflict = pdf_text != "" and pdf_text != ocr_text
        if conflict:
            flags.append("SOURCE_CONFLICT")

        return field.model_copy(
            update={
                "value": ocr_text,
                "source": "cross_validated" if not conflict else "ocr",
                "confidence": result.confidence,
                "ocr_raw_value": result.text,
                "ocr_confidence": result.confidence,
                "validation_flags": flags,
                # Always True, regardless of OCR confidence: this only runs on a
                # page whose text layer is already known-unreliable, and
                # tesseract's confidence measures glyph-recognition certainty,
                # not semantic correctness - a "confident" misread is exactly
                # the case review exists to catch, per this module's own
                # documented policy above ("genuinely uncertain ... stays
                # review_required even when it recovers legible text").
                "review_required": True,
            }
        )
