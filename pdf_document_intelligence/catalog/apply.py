"""Applies authoritative Master-catalog product names by barcode.

Catalog resolution preserves PDF/OCR evidence.  Callers may defer non-product
classification until after OCR by setting classify=False.
"""
from __future__ import annotations

import re
import unicodedata

from pdf_document_intelligence.catalog.classify import classify_product
from pdf_document_intelligence.catalog.loader import CatalogEntry
from pdf_document_intelligence.models.document import TableRow
from pdf_document_intelligence.tables.fields import compute_confidence_band


def _normalized_name(text: object) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    return re.sub(r"\s+", " ", value).strip()


def apply_catalog_to_row(
    row: TableRow, catalog: dict[str, CatalogEntry], *, classify: bool = True
) -> TableRow:
    name_field = row.fields.get("name")
    barcode_field = row.fields.get("barcode")
    barcode = str(barcode_field.value) if barcode_field and barcode_field.value else None
    entry = catalog.get(barcode) if barcode else None

    fields = dict(row.fields)
    classification_name = name_field.value if name_field else None

    if entry and name_field:
        classification_name = entry.name
        extracted_name = _normalized_name(name_field.value)
        master_name = _normalized_name(entry.name)
        flags = ["CATALOG_MATCH"]
        if extracted_name and master_name and extracted_name != master_name:
            flags.append("CATALOG_NAME_MISMATCH")
        fields["name"] = name_field.model_copy(
            update={
                "value": entry.name,
                "source": "master_catalog",
                "confidence": 1.0,
                "review_required": False,
                "validation_flags": flags,
            }
        )
    elif barcode and name_field:
        fields["name"] = name_field.model_copy(
            update={"validation_flags": [*name_field.validation_flags, "CATALOG_CHECKED_NOT_FOUND"]}
        )

    if not classify:
        return row.model_copy(
            update={"fields": fields, "confidence_band": compute_confidence_band(fields)}
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
