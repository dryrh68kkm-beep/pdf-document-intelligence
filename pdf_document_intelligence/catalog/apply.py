"""Applies the master catalog to a parsed row: authoritative name lookup
by barcode (overrides OCR/PDF-text `name` when found — higher confidence
than either, since it's an exact match against real master data, not a
pixel/glyph reading) plus the conservative non-product classification.

`raw_value` and any `ocr_raw_value` on the field are left untouched even
when overridden — the catalog match is additive evidence, not a deletion
of what extraction actually saw.
"""
from __future__ import annotations

from pdf_document_intelligence.catalog.classify import classify_product
from pdf_document_intelligence.catalog.loader import CatalogEntry
from pdf_document_intelligence.models.document import TableRow
from pdf_document_intelligence.tables.fields import compute_confidence_band


def apply_catalog_to_row(row: TableRow, catalog: dict[str, CatalogEntry]) -> TableRow:
    name_field = row.fields.get("name")
    barcode_field = row.fields.get("barcode")
    barcode = str(barcode_field.value) if barcode_field and barcode_field.value else None
    entry = catalog.get(barcode) if barcode else None

    fields = dict(row.fields)
    classification_name = name_field.value if name_field else None

    if entry and name_field:
        classification_name = entry.name
        fields["name"] = name_field.model_copy(
            update={
                "value": entry.name,
                "source": "master_catalog",
                "confidence": 1.0,
                "review_required": False,
                "validation_flags": ["CATALOG_MATCH"],
            }
        )

    classification = classify_product(classification_name)
    return row.model_copy(
        update={
            "fields": fields,
            "confidence_band": compute_confidence_band(fields),
            "suspected_non_product": classification.suspected_non_product,
            "non_product_reasons": classification.reasons,
        }
    )
