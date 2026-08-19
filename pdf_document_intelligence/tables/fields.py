"""FieldParser: RawRow (geometry-assigned text cells) -> typed FieldValue
objects with bounding box, source, and confidence — the point where
"text with a position" becomes "evidence for a value" (proposal §61).
"""
from __future__ import annotations

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.extract.text import PageText, TextQuality
from pdf_document_intelligence.models.document import BoundingBox, FieldValue, TableRow
from pdf_document_intelligence.normalize.thai import normalize_thai_text
from pdf_document_intelligence.normalize.types import TypeParseError, parse_integer, parse_number
from pdf_document_intelligence.tables.geometry import Cell, RawRow
from pdf_document_intelligence.templates.base import ColumnSpec
from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS as BIGC_COLUMNS

_THAI_RANGE = range(0x0E01, 0x0E5C)


def _has_thai(text: str) -> bool:
    return any(ord(c) in _THAI_RANGE for c in text)


def _bbox(cell: Cell, page: int) -> BoundingBox:
    if not cell.words:
        return BoundingBox(x=0, y=0, width=0, height=0, page=page)
    x0 = min(w.x0 for w in cell.words)
    x1 = max(w.x1 for w in cell.words)
    top = min(w.top for w in cell.words)
    bottom = max(w.bottom for w in cell.words)
    return BoundingBox(x=x0, y=top, width=x1 - x0, height=bottom - top, page=page)


def _parse_field(
    canonical_name: str,
    field_type: str,
    raw_text: str,
    bbox: BoundingBox,
    page_quality: TextQuality,
    settings: Settings,
    required: bool = True,
) -> FieldValue:
    raw_text = raw_text.strip()
    normalized = normalize_thai_text(raw_text)
    value: str | int | float | None
    validation_flags: list[str] = []
    review_required = False
    confidence = 0.99 if raw_text else 0.5

    if not normalized and not required:
        # A genuinely optional column (e.g. REMARKS) being blank is a real,
        # confidently-observed value — not a missing-field defect.
        return FieldValue(
            name=canonical_name,
            raw_value=raw_text,
            value=None,
            type=field_type,  # type: ignore[arg-type]
            bbox=bbox,
            source="pdf_text",
            confidence=1.0,
            validation_flags=[],
            review_required=False,
        )

    if field_type == "code" or field_type == "string":
        value = normalized if normalized else None
        if not normalized:
            confidence = 0.0
            review_required = True
            validation_flags.append("MISSING_FIELD")
    elif field_type == "integer":
        try:
            value = parse_integer(normalized) if normalized else None
            if value is None:
                confidence = 0.0
                review_required = True
                validation_flags.append("MISSING_FIELD")
        except TypeParseError:
            value = None
            confidence = 0.2
            review_required = True
            validation_flags.append("TYPE_PARSE_FAILED")
    elif field_type == "decimal":
        try:
            value = parse_number(normalized) if normalized else None
            if value is None:
                confidence = 0.0
                review_required = True
                validation_flags.append("MISSING_FIELD")
        except TypeParseError:
            value = None
            confidence = 0.2
            review_required = True
            validation_flags.append("TYPE_PARSE_FAILED")
    else:
        value = normalized

    # Thai text sourced from a page whose text layer we've already flagged
    # unreliable (combining marks silently dropped, see extract/text.py) can
    # never be auto-approved — this is "ไม่แน่ใจ = ห้ามเดา" made concrete.
    if _has_thai(normalized) and not page_quality.reliable:
        confidence = min(confidence, 0.4)
        review_required = True
        if "TEXT_LAYER_UNRELIABLE" not in validation_flags:
            validation_flags.append("TEXT_LAYER_UNRELIABLE")

    return FieldValue(
        name=canonical_name,
        raw_value=raw_text,
        value=value,
        type=field_type,  # type: ignore[arg-type]
        bbox=bbox,
        source="pdf_text",
        confidence=confidence,
        validation_flags=validation_flags,
        review_required=review_required,
    )


def parse_row(
    raw_row: RawRow,
    row_index: int,
    page_quality_by_page: dict[int, TextQuality],
    settings: Settings,
    group_carry: dict[str, str],
    columns: tuple[ColumnSpec, ...] = BIGC_COLUMNS,
) -> TableRow:
    fields: dict[str, FieldValue] = {}
    page_quality = page_quality_by_page[raw_row.page]

    for col in columns:
        cell = raw_row.cells.get(col.canonical_name)
        raw_text = cell.text.strip() if cell else ""
        bbox = _bbox(cell, raw_row.page) if cell else BoundingBox(x=0, y=0, width=0, height=0, page=raw_row.page)

        if col.is_group_key:
            if raw_text:
                group_carry[col.canonical_name] = raw_text
            else:
                raw_text = group_carry.get(col.canonical_name, "")

        field = _parse_field(col.canonical_name, col.field_type, raw_text, bbox, page_quality, settings, col.required)
        fields[col.canonical_name] = field

    return TableRow(row_index=row_index, fields=fields, confidence_band=compute_confidence_band(fields))


def compute_confidence_band(fields: dict[str, FieldValue]) -> str:
    confidences = [f.confidence for f in fields.values()]
    avg = sum(confidences) / len(confidences) if confidences else 0.0
    if avg >= 0.9 and not any(f.review_required for f in fields.values()):
        return "HIGH"
    if avg >= 0.6:
        return "MEDIUM"
    return "LOW"
