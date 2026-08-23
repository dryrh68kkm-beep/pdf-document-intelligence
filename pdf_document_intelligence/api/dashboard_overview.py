"""Cross-document dashboard overview for the Phase 4 home page.

The frontend previously fetched one Division summary per visible document and
aggregated them in JavaScript. That scales linearly in HTTP requests as the
document library grows. This module performs the same evidence-aware rollup in
one backend pass over active completed documents and product rows.

Filtering is based only on ``meta_json.documentDate`` extracted from the
business document. Upload timestamps are never used as a substitute.
"""
from __future__ import annotations

import json
from decimal import Decimal

from fastapi import HTTPException

from pdf_document_intelligence.db.repository import Repository
from pdf_document_intelligence.templates.department_groups import (
    division_for_department,
    get_default_divisions,
)


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _document_date(doc: dict) -> str | None:
    if doc.get("status") != "complete" or not doc.get("meta_json"):
        return None
    try:
        meta = json.loads(doc["meta_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    value = meta.get("documentDate")
    return value if isinstance(value, str) and value else None


def _date_matches(document_date: str | None, date_from: str | None, date_to: str | None) -> bool:
    if not date_from and not date_to:
        return True
    if not document_date:
        return False
    if date_from and document_date < date_from:
        return False
    if date_to and document_date > date_to:
        return False
    return True


def build_dashboard_overview(
    repo: Repository,
    *,
    date_from: str | None = None,
    date_to: str | None = None,
    division: str | None = None,
) -> dict:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(400, "date_from must be less than or equal to date_to")

    divisions = get_default_divisions()
    division_names = dict(divisions)
    division_filter = None if not division or division == "all" else division
    if division_filter and division_filter not in division_names:
        raise HTTPException(404, f"unknown division '{division_filter}'")

    active_docs: dict[str, dict] = {}
    for doc in repo.list_documents():
        if doc.get("status") != "complete":
            continue
        document_date = _document_date(doc)
        if not _date_matches(document_date, date_from, date_to):
            continue
        active_docs[doc["id"]] = doc

    buckets = {
        code: {
            "rowCount": 0,
            "amount": Decimal("0"),
            "documentIds": set(),
        }
        for code, _ in divisions
    }

    all_rows = 0
    all_amount = Decimal("0")
    amount_available = False

    for row in repo.list_product_rows():
        doc_id = row["document_id"]
        if doc_id not in active_docs or row.get("suspected_non_product"):
            continue

        all_rows += 1
        row_amount = row.get("amount")
        if row_amount is not None:
            amount_available = True
            all_amount += _money(row_amount)

        mapped = division_for_department(row["department"])
        if mapped is None:
            continue
        code, _ = mapped
        bucket = buckets[code]
        bucket["rowCount"] += 1
        bucket["documentIds"].add(doc_id)
        if row_amount is not None:
            bucket["amount"] += _money(row_amount)

    division_list = [
        {
            "divisionCode": code,
            "divisionName": name,
            "rowCount": buckets[code]["rowCount"],
            "amount": float(buckets[code]["amount"].quantize(Decimal("0.01"))),
            "documentCount": len(buckets[code]["documentIds"]),
        }
        for code, name in divisions
    ]

    if division_filter:
        selected = next(item for item in division_list if item["divisionCode"] == division_filter)
        totals = {
            "rowCount": selected["rowCount"],
            "amount": selected["amount"],
            "documentCount": selected["documentCount"],
        }
    else:
        totals = {
            "rowCount": all_rows,
            "amount": float(all_amount.quantize(Decimal("0.01"))),
            "documentCount": len(active_docs),
        }

    return {
        "filters": {
            "dateFrom": date_from or "",
            "dateTo": date_to or "",
            "division": division_filter or "all",
        },
        "totals": totals,
        "divisions": division_list,
        "amountAvailable": amount_available,
        "selectedDivision": division_filter or "all",
    }
