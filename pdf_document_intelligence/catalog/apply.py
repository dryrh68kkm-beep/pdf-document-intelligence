"""Applies the master catalog to a parsed row: authoritative name lookup
by barcode (overrides OCR/PDF-text `name` when found — higher confidence
than either, since it's an exact match against real master data, not a
pixel/glyph reading) plus the conservative non-product classification.

`raw_value` and any `ocr_raw_value` on the field are left untouched even
when overridden — the catalog match is additive evidence, not a deletion
of what extraction actually saw.
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


def apply_catalog_to_row(row: TableRow, catalog: dict[str, CatalogEntry]) -> TableRow:
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

        # Exact barcode lookup remains authoritative. A different source name
        # is retained as audit evidence because Thai text layers/OCR can be
        # imperfect, but it must not downgrade an exact catalog match into a
        # manual-review item. Identifier/geometry validation is responsible
        # for deciding whether the barcode itself is trustworthy.
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
        # No silent gap: record that a lookup was actually attempted and
        # came back empty, so the UI can tell "checked against Official
        # Master, genuinely not there" apart from "never checked" (user
        # report: the review panel explained OCR/font issues but never
        # said whether the barcode had been checked against the master
        # file at all).
        fields["name"] = name_field.model_copy(
            update={"validation_flags": [*name_field.validation_flags, "CATALOG_CHECKED_NOT_FOUND"]}
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
