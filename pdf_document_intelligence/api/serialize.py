"""Flattens SQLite repository rows into the JSON shape the SPA consumes.

A product's `fields` dict merges two things: the *original extraction
evidence* (raw PDF text, OCR text/confidence, bbox) frozen in
`fields_json` at extraction time, and the *current effective value* which
is the repository column (`resolved_product_name`, `weight_qty`, ...) -
the column is what a correction updates, so a corrected row shows the
corrected value with the original evidence still attached underneath it.
"""
from __future__ import annotations

import json

from pdf_document_intelligence.db.field_columns import FIELD_TO_COLUMN as _EDITABLE_FIELD_COLUMN
from pdf_document_intelligence.templates.packing_list_bigc import RECONCILIATION_COLUMNS

NUMERIC_COLUMNS = list(RECONCILIATION_COLUMNS)
IDENTITY_COLUMN = "article"


def _row_id(row: dict) -> str:
    return row["id"]


def document_summary_json(doc: dict, row_stats: dict | None = None) -> dict:
    base = {
        "id": doc["id"],
        "filename": doc["filename"],
        "status": doc["status"],
        "uploadedAt": doc["uploaded_at"],
        "progress": {
            "stage": doc["progress_stage"],
            "current": doc["progress_current"],
            "total": doc["progress_total"],
        },
        "error": doc["error"],
    }
    if doc["status"] == "complete" and doc.get("meta_json"):
        meta = json.loads(doc["meta_json"])
        stats = row_stats or {}
        quality = meta.get("quality") or {}
        base.update(
            {
                "pages": doc["page_count"],
                "documentType": meta.get("documentType"),
                "confidence": round(meta["confidence"], 2) if meta.get("confidence") is not None else None,
                "status_document": meta.get("statusDocument"),
                "reconciled": meta.get("reconciled"),
                "qualityScore": quality.get("score"),
                "qualityBand": quality.get("band"),
                "qualityBreakdown": quality.get("breakdown", {}),
                "qualityCounts": {
                    "rows": quality.get("row_count", 0),
                    "verified": quality.get("verified_rows", 0),
                    "needReview": quality.get("review_rows", 0),
                    "errors": quality.get("error_count", 0),
                    "warnings": quality.get("warning_count", 0),
                    "masterMatched": quality.get("master_matched_rows", 0),
                },
                "errors": sum(1 for i in meta.get("validationIssues", []) if i["severity"] == "error"),
                "warnings": sum(1 for i in meta.get("validationIssues", []) if i["severity"] == "warning"),
                "rowCount": stats.get("rowCount", 0),
                "departmentCount": stats.get("departmentCount", 0),
                "reviewCount": stats.get("reviewCount", 0),
                "totalAmount": stats.get("totalAmount"),
                "documentDate": meta.get("documentDate"),
                "documentDateEvidence": meta.get("documentDateEvidence"),
            }
        )
    return base


def _field_json(field_name: str, fv_json: dict | None, row: dict) -> dict:
    fv_json = dict(fv_json or {})
    column = _EDITABLE_FIELD_COLUMN.get(field_name)
    current_value = row.get(column) if column else fv_json.get("value")
    return {
        "value": current_value,
        "raw": fv_json.get("raw_value"),
        "type": fv_json.get("type"),
        "source": fv_json.get("source"),
        "confidence": round(fv_json["confidence"], 3) if fv_json.get("confidence") is not None else None,
        "review": bool(fv_json.get("review_required")),
        "flags": fv_json.get("validation_flags", []),
        "page": fv_json.get("bbox", {}).get("page"),
        "bbox": fv_json.get("bbox"),
        "ocrRaw": fv_json.get("ocr_raw_value"),
        "ocrConfidence": round(fv_json["ocr_confidence"], 3) if fv_json.get("ocr_confidence") is not None else None,
        "corrected": current_value != fv_json.get("value") if column else False,
    }


def product_row_json(row: dict, doc_filename: str) -> dict:
    fields_raw = json.loads(row["fields_json"])
    fields = {name: _field_json(name, fv, row) for name, fv in fields_raw.items()}
    return {
        "rowId": _row_id(row),
        "docId": row["document_id"],
        "docFilename": doc_filename,
        "department": row["department"],
        "page": row["source_page"],
        "band": row["confidence_band"],
        "reviewRequired": bool(row["review_required"]),
        "reviewReasons": json.loads(row.get("review_reasons") or "[]"),
        "resolutionStatus": row["resolution_status"],
        "suspectedNonProduct": bool(row["suspected_non_product"]),
        "nonProductReasons": json.loads(row.get("non_product_reasons") or "[]"),
        "fields": fields,
        # PR12: the version token a client echoes back on PATCH
        # (expectedUpdatedAt) so a second editor's concurrent save on the
        # same row is rejected instead of silently overwriting the first.
        "updatedAt": row["updated_at"],
    }


def document_detail_json(doc: dict, product_rows: list[dict]) -> dict:
    stats = _row_stats(product_rows)
    detail = document_summary_json(doc, stats)
    if doc["status"] != "complete" or not doc.get("meta_json"):
        return detail
    meta = json.loads(doc["meta_json"])
    detail["numericColumns"] = NUMERIC_COLUMNS
    detail["engineVersion"] = meta.get("engineVersion")
    detail["ocrEngineVersion"] = meta.get("ocrEngineVersion")
    detail["templateVersion"] = meta.get("templateVersion")
    detail["processingLog"] = meta.get("processingLog", [])
    detail["validationIssues"] = meta.get("validationIssues", [])
    detail["products"] = [product_row_json(r, doc["filename"]) for r in product_rows]
    return detail


def _row_stats(product_rows: list[dict]) -> dict:
    departments = {r["department"] for r in product_rows}
    review_count = sum(1 for r in product_rows if r["review_required"])
    total_amount = sum(r["amount"] for r in product_rows if r.get("amount") is not None)
    return {
        "rowCount": len(product_rows),
        "departmentCount": len(departments),
        "reviewCount": review_count,
        "totalAmount": round(total_amount, 2) if any(r.get("amount") is not None for r in product_rows) else None,
    }


def all_products_json(docs_with_rows: list[tuple[dict, list[dict]]]) -> list[dict]:
    products: list[dict] = []
    for doc, rows in docs_with_rows:
        if doc["status"] == "complete":
            products.extend(product_row_json(r, doc["filename"]) for r in rows)
    return products
