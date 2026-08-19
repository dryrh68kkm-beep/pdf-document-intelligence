"""Central recalculation engine: the only place dashboard/department/grand
summaries get computed. Both `/api/state` and any per-document view call
into here - dashboard logic must never be duplicated in the frontend, so an
edit (quantity, department move, ...) recalculates by re-running this
against the current SQLite rows, never by patching a cached number in JS.

Aggregates only over numeric fields that actually exist for this document
type (weight_qty/pu_qty/sku_qty for a packing list; unit_price/amount stay
None and are simply skipped when a future invoice-type template populates
them) - never fabricates a total that isn't backed by extracted evidence.
"""
from __future__ import annotations

from collections import defaultdict

from pdf_document_intelligence.db.repository import Repository
from pdf_document_intelligence.templates.department_groups import major_department_for
from pdf_document_intelligence.templates.packing_list_bigc import RECONCILIATION_COLUMNS

NUMERIC_COLUMNS = list(RECONCILIATION_COLUMNS)
NUMERIC_LABELS = {"weight_qty": "น้ำหนักรวม (กก.)", "pu_qty": "PU รวม", "sku_qty": "SKU qty รวม"}
RESOLUTION_LABELS = {
    "OFFICIAL_MASTER": "Official Master",
    "LOCAL_MASTER": "Local Master",
    "OCR": "OCR/PDF",
    "MANUAL_REVIEW": "Review",
    "CORRECTED": "แก้ไขแล้ว",
}


def build_dashboard_state(repo: Repository) -> dict:
    docs = repo.list_documents()
    all_rows = repo.list_product_rows()

    dept_skus: dict[str, set[str]] = defaultdict(set)
    dept_totals: dict[str, dict[str, float]] = defaultdict(lambda: {c: 0.0 for c in NUMERIC_COLUMNS})
    dept_review: dict[str, int] = defaultdict(int)
    dept_rows: dict[str, int] = defaultdict(int)
    dept_non_product: dict[str, int] = defaultdict(int)
    grand_totals: dict[str, float] = {c: 0.0 for c in NUMERIC_COLUMNS}
    resolution_counts: dict[str, int] = defaultdict(int)
    review_items: list[dict] = []
    non_product_items: list[dict] = []
    total_rows = 0

    doc_filename = {d["id"]: d["filename"] for d in docs}

    for row in all_rows:
        if row["suspected_non_product"]:
            dept_non_product[row["department"]] += 1
            non_product_items.append(
                {
                    "rowId": row["id"], "docId": row["document_id"],
                    "docFilename": doc_filename.get(row["document_id"]),
                    "department": row["department"], "name": row["resolved_product_name"],
                    "reasons": _json_list(row.get("non_product_reasons")), "page": row["source_page"],
                }
            )
            continue

        total_rows += 1
        dept_rows[row["department"]] += 1
        resolution_counts[row["resolution_status"]] += 1
        identity = row["identity_code"]
        if identity:
            dept_skus[row["department"]].add(identity)

        if row["review_required"]:
            dept_review[row["department"]] += 1
            review_items.append(
                {
                    "rowId": row["id"], "docId": row["document_id"],
                    "docFilename": doc_filename.get(row["document_id"]),
                    "department": row["department"], "name": row["resolved_product_name"],
                    "band": row["confidence_band"], "flags": _json_list(row.get("review_reasons")),
                    "page": row["source_page"], "priority": _review_priority(row),
                }
            )

        for col in NUMERIC_COLUMNS:
            val = row.get(col)
            if val is not None:
                dept_totals[row["department"]][col] += val
                grand_totals[col] += val

    review_items.sort(key=lambda i: i["priority"])

    all_dept_names = set(dept_rows) | set(dept_non_product)
    departments = [
        {
            "name": name,
            "majorDepartment": major_department_for(name),
            "skuCount": len(dept_skus[name]),
            "rowCount": dept_rows[name],
            "reviewCount": dept_review[name],
            "nonProductCount": dept_non_product[name],
            "totals": {c: round(v, 3) for c, v in dept_totals[name].items()},
        }
        for name in all_dept_names
    ]
    departments.sort(key=lambda d: d["totals"].get("sku_qty", 0), reverse=True)

    resolved_total = sum(resolution_counts.values()) or 1
    master_coverage = [
        {
            "status": status, "label": RESOLUTION_LABELS.get(status, status),
            "count": resolution_counts.get(status, 0),
            "percent": round(100 * resolution_counts.get(status, 0) / resolved_total, 1),
        }
        for status in ("OFFICIAL_MASTER", "LOCAL_MASTER", "OCR", "MANUAL_REVIEW", "CORRECTED")
        if resolution_counts.get(status)
    ]

    return {
        "documentCount": len(docs),
        "completedCount": sum(1 for d in docs if d["status"] == "complete"),
        "processingCount": sum(1 for d in docs if d["status"] == "processing"),
        "errorCount": sum(1 for d in docs if d["status"] == "error"),
        "departmentCount": len(departments),
        "skuCount": len({s for skus in dept_skus.values() for s in skus}),
        "rowCount": total_rows,
        "reviewCount": len(review_items),
        "nonProductCount": len(non_product_items),
        "numericColumns": [{"key": c, "label": NUMERIC_LABELS.get(c, c)} for c in NUMERIC_COLUMNS],
        "grandTotals": {c: round(v, 3) for c, v in grand_totals.items()},
        "departments": departments,
        "reviewItems": review_items,
        "nonProductItems": non_product_items,
        "masterCoverage": master_coverage,
    }


# Review Queue Intelligence (spec P4): sort so rows that affect reconciled
# totals surface first, over merely-low-confidence text.
_REASON_PRIORITY = {
    "INVALID_IDENTIFIER": 0, "UNKNOWN_BARCODE": 0, "DEPARTMENT_CONFLICT": 0,
    "AMOUNT_MISMATCH": 1,
    "MISSING_QUANTITY": 2, "MISSING_AMOUNT": 2,
    "OCR_CONFLICT": 3, "SOURCE_CONFLICT": 3,
}


def _review_priority(row: dict) -> int:
    reasons = _json_list(row.get("review_reasons"))
    ranks = [_REASON_PRIORITY.get(r, 4) for r in reasons]
    return min(ranks, default=4)


def _json_list(raw) -> list:
    import json

    if not raw:
        return []
    return json.loads(raw) if isinstance(raw, str) else raw
