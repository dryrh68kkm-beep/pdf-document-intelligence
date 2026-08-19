"""Flattens a pipeline `DocumentResult` (nested Pydantic tables/rows/fields)
into the flat dicts the SQLite repository stores, and applies the
resolution-priority chain for the `name` field:

    Official Master (exact barcode)  -- already applied in catalog/apply.py
        -> Local Verified Master (exact barcode)
        -> Official Master (article/SKU)  [not modeled by this doc type yet]
        -> Local Master (article/SKU)
        -> PDF/OCR reading already on the field
        -> Manual Review

The pipeline itself (pdf_document_intelligence/pipeline/*) stays DB-free -
this module is the only place that reads local_product_master, keeping the
extraction engine pure/offline/deterministic and the "which DB row did we
resolve against" concern in the API layer only.
"""
from __future__ import annotations

from pdf_document_intelligence.db.repository import Repository
from pdf_document_intelligence.models.document import ExtractedTable, TableRow


def _identity_code(fields: dict) -> str | None:
    article = fields.get("article")
    if article and article.value:
        return str(article.value)
    barcode = fields.get("barcode")
    if barcode and barcode.value:
        return str(barcode.value)
    return None


def resolve_local_master(row: TableRow, repo: Repository) -> TableRow:
    """Second-pass resolution after the official catalog: if `name` is
    still an OCR/pdf_text reading (official catalog had no match) and the
    barcode is a known Local Verified Master entry, promote it - same
    ground-truth treatment as an official match, just a different source
    label so the UI can tell them apart."""
    name_field = row.fields.get("name")
    barcode_field = row.fields.get("barcode")
    if not name_field or name_field.source == "master_catalog":
        return row
    barcode = str(barcode_field.value) if barcode_field and barcode_field.value else None
    if not barcode:
        return row
    entry = repo.find_local_master_by_barcode(barcode)
    if not entry:
        return row
    fields = dict(row.fields)
    fields["name"] = name_field.model_copy(
        update={
            "value": entry["product_name"],
            "source": "master_catalog",
            "confidence": 1.0,
            "review_required": False,
            "validation_flags": [*name_field.validation_flags, "LOCAL_MASTER_MATCH"],
        }
    )
    return row.model_copy(update={"fields": fields})


def _resolution_status(row: TableRow) -> str:
    name_field = row.fields.get("name")
    if not name_field:
        return "MANUAL_REVIEW"
    if name_field.source == "master_catalog":
        flags = name_field.validation_flags
        if "LOCAL_MASTER_MATCH" in flags:
            return "LOCAL_MASTER"
        return "OFFICIAL_MASTER"
    if any(fv.review_required for fv in row.fields.values()):
        return "MANUAL_REVIEW"
    return "OCR"


def flatten_row(document_id: str, table: ExtractedTable, row: TableRow) -> dict:
    f = row.fields
    name_field = f.get("name")
    barcode_field = f.get("barcode")
    article_field = f.get("article")

    def num(key: str) -> float | None:
        fv = f.get(key)
        return fv.value if fv and isinstance(fv.value, (int, float)) else None

    review_required = any(fv.review_required for fv in f.values())
    review_reasons = sorted({flag for fv in f.values() for flag in fv.validation_flags if fv.review_required})

    return {
        "source_page": name_field.bbox.page if name_field else table.page_start,
        "row_index": row.row_index,
        "department": table.name,
        "barcode": str(barcode_field.value) if barcode_field and barcode_field.value else None,
        "article_code": str(article_field.value) if article_field and article_field.value else None,
        "identity_code": _identity_code(f),
        "raw_product_name": name_field.raw_value if name_field else None,
        "ocr_product_name": name_field.ocr_raw_value if name_field else None,
        "resolved_product_name": name_field.value if name_field else None,
        "weight_qty": num("weight_qty"),
        "pu_qty": num("pu_qty"),
        "sku_qty": num("sku_qty"),
        "unit": None,
        "unit_price": None,
        "amount": None,
        "confidence": name_field.confidence if name_field else None,
        "confidence_band": row.confidence_band,
        "resolution_status": _resolution_status(row),
        "review_required": review_required,
        "review_reasons": review_reasons,
        "suspected_non_product": row.suspected_non_product,
        "non_product_reasons": row.non_product_reasons,
        "fields": {name: fv.model_dump(mode="json") for name, fv in f.items()},
    }


def persist_document_result(document_id: str, result, repo: Repository) -> dict:
    """Applies local-master resolution then writes all rows for this
    document via the repository's reprocess-safe replace."""
    flat_rows: list[dict] = []
    for table in result.tables:
        for row in table.rows:
            resolved = resolve_local_master(row, repo)
            flat_rows.append(flatten_row(document_id, table, resolved))
    return repo.replace_document_rows(document_id, flat_rows)
