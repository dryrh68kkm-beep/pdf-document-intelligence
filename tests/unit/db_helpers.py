"""Shared helper to build a small synthetic DocumentResult (no PDF/OCR
needed) for exercising the persistence/review/aggregation layers fast -
extraction correctness itself stays covered by the golden regression
tests against real PDFs."""
from __future__ import annotations

from datetime import datetime, timezone

from pdf_document_intelligence.models.document import (
    BoundingBox, DocumentResult, ExtractedTable, FieldValue, TableRow, ValidationSummary,
)


def _fv(name, value, *, source="pdf_text", confidence=0.99, review=False, flags=None, page=1):
    return FieldValue(
        name=name, raw_value=str(value) if value is not None else "", value=value, type="string",
        bbox=BoundingBox(x=0, y=0, width=1, height=1, page=page), source=source,
        confidence=confidence, validation_flags=flags or [], review_required=review,
    )


def make_row(row_index, department, barcode, article, name, weight_qty, pu_qty, sku_qty, *, review=False, flags=None):
    fields = {
        "barcode": _fv("barcode", barcode),
        "article": _fv("article", article),
        "name": _fv("name", name, review=review, flags=flags or []),
        "weight_qty": _fv("weight_qty", weight_qty),
        "pu_qty": _fv("pu_qty", pu_qty),
        "sku_qty": _fv("sku_qty", sku_qty),
    }
    band = "LOW" if review else "HIGH"
    return TableRow(row_index=row_index, fields=fields, confidence_band=band)


def make_result(doc_id, filename, tables: list[tuple[str, list[TableRow]]]) -> DocumentResult:
    extracted = [
        ExtractedTable(name=dept, page_start=1, page_end=1, header=[], rows=rows, source_pages=[1])
        for dept, rows in tables
    ]
    total_rows = sum(len(rows) for _, rows in tables)
    return DocumentResult(
        id=doc_id, filename=filename, pages=1, document_type="packing_list_bigc_cdc",
        engine_version="test", ocr_engine_version="test", parser_version="test",
        template_version="v1", confidence=0.97, status="AUTO_APPROVED",
        tables=extracted, fields=[],
        validation=ValidationSummary(reconciled=True, errors=[], warnings=[]),
        processing_log=[],
    )
