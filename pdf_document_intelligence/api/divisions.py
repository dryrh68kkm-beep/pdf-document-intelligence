"""Division-level analytics (Dashboard Phase 1): the only place the
Division -> Department -> Product rollup gets computed. Always scoped to
one document (the Dashboard shows one packing list at a time), always
sourced from data/master_catalog.csv via
templates/department_groups.py - never a hand-typed division list.

Mirrors aggregate.py's rule: this is the single source of truth for these
numbers, the frontend only renders what this module returns. Corrected
values are used automatically because they're read straight off the
product_rows columns a correction writes to (see db/field_columns.py) -
no separate "corrected" branch needed. Soft-deleted documents/rows are
excluded by repo.get_document/list_product_rows already filtering
deleted_at, and a reprocess replaces rows in place (db/repository.py
_replace_document_rows_sql) rather than adding new ones, so this module
never has to reason about double-counting itself.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from fastapi import HTTPException

from pdf_document_intelligence.db.repository import Repository
from pdf_document_intelligence.templates.department_groups import (
    division_for_department,
    get_default_divisions,
)
from pdf_document_intelligence.templates.packing_list_bigc import RECONCILIATION_COLUMNS

NUMERIC_COLUMNS = list(RECONCILIATION_COLUMNS)  # weight_qty, pu_qty, sku_qty


def _decimal(val) -> Decimal | None:
    """Money must never round-trip through float - the DB driver hands us
    a Python float (SQLite REAL affinity), so convert via str() rather than
    Decimal(float) directly to avoid inheriting float's binary imprecision."""
    if val is None:
        return None
    return Decimal(str(val))


def _active_document(repo: Repository, doc_id: str) -> dict:
    doc = repo.get_document(doc_id)
    if not doc or doc.get("deleted_at") is not None:
        raise HTTPException(404, "document not found")
    return doc


def _reconciliation(doc: dict) -> dict:
    import json

    if doc["status"] != "complete" or not doc.get("meta_json"):
        return {"status": None, "errors": 0}
    meta = json.loads(doc["meta_json"])
    return {
        "status": "PASSED" if meta.get("reconciled") else "FAILED",
        "errors": sum(1 for i in meta.get("validationIssues", []) if i["severity"] == "error"),
    }


def build_division_summary(repo: Repository, doc_id: str) -> dict:
    doc = _active_document(repo, doc_id)
    rows = repo.list_product_rows(document_id=doc_id)

    divisions = get_default_divisions()  # ordered (code, bare_name), always exactly the 6
    buckets = {
        code: {
            "rowCount": 0, "weight": 0.0, "puQty": 0.0, "skuQty": 0.0,
            "amount": Decimal("0"), "reviewCount": 0, "departments": set(),
        }
        for code, _ in divisions
    }

    unmapped_departments: set[str] = set()
    unmapped_row_count = 0
    unmapped_amount = Decimal("0")
    doc_totals = {c: 0.0 for c in NUMERIC_COLUMNS}
    doc_amount = Decimal("0")
    doc_row_count = 0
    review_required = 0
    corrected = 0
    resolved_master = 0
    resolved_ocr = 0
    unresolved = 0
    clean_rows = 0

    for row in rows:
        if row["suspected_non_product"]:
            continue

        doc_row_count += 1
        if row["review_required"]:
            review_required += 1
        status = row["resolution_status"]
        if status == "CORRECTED":
            corrected += 1
        elif status in ("OFFICIAL_MASTER", "LOCAL_MASTER"):
            resolved_master += 1
        elif status == "OCR":
            resolved_ocr += 1
        elif status == "MANUAL_REVIEW":
            unresolved += 1
        if not row["review_required"] and status != "MANUAL_REVIEW":
            clean_rows += 1

        for col in NUMERIC_COLUMNS:
            val = row.get(col)
            if val is not None:
                doc_totals[col] += val
        row_amount = _decimal(row.get("amount"))
        if row_amount is not None:
            doc_amount += row_amount

        division = division_for_department(row["department"])
        if division is None:
            unmapped_departments.add(row["department"])
            unmapped_row_count += 1
            if row_amount is not None:
                unmapped_amount += row_amount
            continue

        code, _ = division
        bucket = buckets[code]
        bucket["rowCount"] += 1
        bucket["departments"].add(row["department"])
        if row["review_required"]:
            bucket["reviewCount"] += 1
        for col in NUMERIC_COLUMNS:
            val = row.get(col)
            if val is not None:
                bucket[{"weight_qty": "weight", "pu_qty": "puQty", "sku_qty": "skuQty"}[col]] += val
        if row_amount is not None:
            bucket["amount"] += row_amount

    division_list = []
    for code, name in divisions:
        b = buckets[code]
        division_list.append(
            {
                "divisionCode": code,
                "divisionName": name,
                "departmentCount": len(b["departments"]),
                "rowCount": b["rowCount"],
                "weight": round(b["weight"], 3),
                "puQty": round(b["puQty"], 3),
                "skuQty": round(b["skuQty"], 3),
                "amount": float(b["amount"].quantize(Decimal("0.01"))),
                "reviewCount": b["reviewCount"],
                "status": "REVIEW" if b["reviewCount"] > 0 else "OK",
            }
        )

    return {
        "documentId": doc_id,
        "documentTotals": {
            "rowCount": doc_row_count,
            "weight": round(doc_totals["weight_qty"], 3),
            "puQty": round(doc_totals["pu_qty"], 3),
            "skuQty": round(doc_totals["sku_qty"], 3),
            "amount": float(doc_amount.quantize(Decimal("0.01"))),
        },
        "divisions": division_list,
        "dataQuality": {
            "cleanRows": clean_rows,
            "reviewRequired": review_required,
            "corrected": corrected,
            "resolvedFromMaster": resolved_master,
            "resolvedFromOcr": resolved_ocr,
            "unresolved": unresolved,
            "unmappedDepartments": sorted(unmapped_departments),
            "unmappedRowCount": unmapped_row_count,
            "unmappedAmount": float(unmapped_amount.quantize(Decimal("0.01"))),
        },
        "reconciliation": _reconciliation(doc),
    }


def build_division_departments(repo: Repository, doc_id: str, division_code: str) -> dict:
    divisions = dict(get_default_divisions())
    if division_code not in divisions:
        raise HTTPException(404, f"unknown division '{division_code}'")

    _active_document(repo, doc_id)
    rows = repo.list_product_rows(document_id=doc_id)

    dept_buckets: dict[str, dict] = defaultdict(
        lambda: {
            "rowCount": 0, "weight": 0.0, "puQty": 0.0, "skuQty": 0.0,
            "amount": Decimal("0"), "reviewCount": 0,
        }
    )

    for row in rows:
        if row["suspected_non_product"]:
            continue
        division = division_for_department(row["department"])
        if division is None or division[0] != division_code:
            continue
        b = dept_buckets[row["department"]]
        b["rowCount"] += 1
        if row["review_required"]:
            b["reviewCount"] += 1
        for col in NUMERIC_COLUMNS:
            val = row.get(col)
            if val is not None:
                b[{"weight_qty": "weight", "pu_qty": "puQty", "sku_qty": "skuQty"}[col]] += val
        row_amount = _decimal(row.get("amount"))
        if row_amount is not None:
            b["amount"] += row_amount

    departments = [
        {
            "name": name,
            "rowCount": b["rowCount"],
            "weight": round(b["weight"], 3),
            "puQty": round(b["puQty"], 3),
            "skuQty": round(b["skuQty"], 3),
            "amount": float(b["amount"].quantize(Decimal("0.01"))),
            "reviewCount": b["reviewCount"],
        }
        for name, b in dept_buckets.items()
    ]
    departments.sort(key=lambda d: d["skuQty"], reverse=True)

    return {
        "documentId": doc_id,
        "divisionCode": division_code,
        "divisionName": divisions[division_code],
        "departments": departments,
    }
