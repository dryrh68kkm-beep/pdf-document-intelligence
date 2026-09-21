"""Flattens a pipeline `DocumentResult` (nested Pydantic tables/rows/fields)
into the flat dicts the SQLite repository stores, and applies the
resolution-priority chain for the `name` field:

    Official Master (exact barcode)  -- already applied in catalog/apply.py
        -> Local Verified Master (exact barcode)
        -> expiry-dashboard's live daily product list (exact barcode)
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

from decimal import Decimal

from pdf_document_intelligence.catalog.expiry_dashboard_lookup import lookup_barcode, resolve_data_path
from pdf_document_intelligence.catalog.loader import get_default_catalog
from pdf_document_intelligence.config.settings import Settings
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


def _catalog_unit_price(barcode: str | None) -> Decimal | None:
    """Real per-item cost from the master catalog (CURRENT_COST column),
    looked up the same way name resolution already matches a row's barcode
    against the same catalog snapshot - not a guess, not an extraction
    change: unit_price/amount were never populated by any packing-list
    template, this is the API layer enriching a resolved barcode with the
    master's own cost figure, same as it already does for `name`."""
    if not barcode:
        return None
    entry = get_default_catalog().get(barcode)
    return entry.unit_cost if entry else None


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


def resolve_expiry_dashboard(row: TableRow, settings: Settings, snapshot_path=None) -> TableRow:
    """Third-pass resolution: if `name` is still unresolved (neither the
    Official nor Local Verified Master had this barcode), check
    expiry-dashboard's own live daily product list
    (catalog/expiry_dashboard_lookup.py) - a hit there means the store's
    POS itself recognizes this exact barcode as a real, currently-stocked
    product today, which is real-world ground truth same as the other two
    tiers, just sourced from the sibling app instead of this app's own
    catalog/DB. Every match is also durable: see
    catalog/expiry_dashboard_snapshot.py - a barcode confirmed once stays
    resolvable even after it drops out of expiry-dashboard's own file.
    `snapshot_path` overrides where that persistent snapshot lives; tests
    pass a tmp_path so they never touch the real app data directory,
    production always uses the real one (leave it unset)."""
    name_field = row.fields.get("name")
    barcode_field = row.fields.get("barcode")
    if not name_field or name_field.source == "master_catalog":
        return row
    barcode = str(barcode_field.value) if barcode_field and barcode_field.value else None
    if not barcode:
        return row
    data_path = resolve_data_path(settings.expiry_dashboard_www_dir)
    entry = lookup_barcode(barcode, data_path, snapshot_path)
    if not entry or not entry.get("description"):
        return row
    fields = dict(row.fields)
    fields["name"] = name_field.model_copy(
        update={
            "value": entry["description"],
            "source": "master_catalog",
            "confidence": 1.0,
            "review_required": False,
            "validation_flags": [*name_field.validation_flags, "EXPIRY_DASHBOARD_MATCH"],
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
        if "EXPIRY_DASHBOARD_MATCH" in flags:
            return "EXPIRY_DASHBOARD"
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

    barcode_value = str(barcode_field.value) if barcode_field and barcode_field.value else None
    sku_qty_value = num("sku_qty")
    unit_cost = _catalog_unit_price(barcode_value)
    unit_price = float(unit_cost) if unit_cost is not None else None
    amount = (
        float((unit_cost * Decimal(str(sku_qty_value))).quantize(Decimal("0.01")))
        if unit_cost is not None and sku_qty_value is not None
        else None
    )
    # unit_price/amount aren't modeled TableRow fields (no packing-list
    # template extracts a price), so f.items() below never carries them -
    # without this the Products table/Evidence panel, which read every
    # field through row["fields"][name], would never see these two at all
    # even though the flat unit_price/amount columns above are correct.
    evidence_page = name_field.bbox.page if name_field else table.page_start
    synthetic_fields = {
        key: {
            "name": key,
            "raw_value": "",
            "value": value,
            "type": "decimal",
            "bbox": {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0, "page": evidence_page},
            "source": "master_catalog" if unit_cost is not None else "pdf_text",
            "confidence": 1.0 if unit_cost is not None else 0.0,
            "validation_flags": ["CATALOG_MATCH"] if unit_cost is not None else [],
            "review_required": False,
            "ocr_raw_value": None,
            "ocr_confidence": None,
        }
        for key, value in (("unit_price", unit_price), ("amount", amount))
    }

    return {
        "source_page": name_field.bbox.page if name_field else table.page_start,
        "row_index": row.row_index,
        "department": table.name,
        "barcode": barcode_value,
        "article_code": str(article_field.value) if article_field and article_field.value else None,
        "identity_code": _identity_code(f),
        "raw_product_name": name_field.raw_value if name_field else None,
        "ocr_product_name": name_field.ocr_raw_value if name_field else None,
        "resolved_product_name": name_field.value if name_field else None,
        "weight_qty": num("weight_qty"),
        "pu_qty": num("pu_qty"),
        "sku_qty": sku_qty_value,
        "unit": None,
        "unit_price": unit_price,
        "amount": amount,
        "confidence": name_field.confidence if name_field else None,
        "confidence_band": row.confidence_band,
        "resolution_status": _resolution_status(row),
        "review_required": review_required,
        "review_reasons": review_reasons,
        "suspected_non_product": row.suspected_non_product,
        "non_product_reasons": row.non_product_reasons,
        "fields": {**{name: fv.model_dump(mode="json") for name, fv in f.items()}, **synthetic_fields},
    }


def prepare_flat_rows(document_id: str, result, repo: Repository, settings: Settings | None = None) -> list[dict]:
    """Applies local-master resolution and flattens every row - the
    DB-write-free half of `persist_document_result`, split out so a caller
    (store.py) can prepare rows and write them + the document's completion
    status in one atomic transaction (see
    `Repository.complete_document_with_rows`)."""
    settings = settings or Settings()
    flat_rows: list[dict] = []
    for table in result.tables:
        for row in table.rows:
            resolved = resolve_local_master(row, repo)
            resolved = resolve_expiry_dashboard(resolved, settings)
            flat_rows.append(flatten_row(document_id, table, resolved))
    return flat_rows


def persist_document_result(document_id: str, result, repo: Repository) -> dict:
    """Applies local-master resolution then writes all rows for this
    document via the repository's reprocess-safe replace."""
    flat_rows = prepare_flat_rows(document_id, result, repo)
    return repo.replace_document_rows(document_id, flat_rows)
