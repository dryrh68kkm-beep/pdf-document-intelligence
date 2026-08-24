"""Editable-review endpoints: validates a PATCH, writes it + its audit
correction record, then re-derives review_required/amount-mismatch flags
for that single row. Dashboard/department numbers are never patched in
place - they're always freshly recomputed by aggregate.py from the rows
this module just wrote, so there is exactly one source of truth.
"""
from __future__ import annotations

import json

from fastapi import HTTPException

from pdf_document_intelligence.db.field_columns import FIELD_TO_COLUMN, NUMERIC_FIELDS
from pdf_document_intelligence.db.repository import Repository

IDENTIFIER_FIELDS = {"barcode", "article"}
EDITABLE_FIELDS = set(FIELD_TO_COLUMN)
_FIELD_TO_COLUMN = FIELD_TO_COLUMN
_NUMERIC_FIELDS = NUMERIC_FIELDS


def validate_patch(field_name: str, new_value) -> None:
    if field_name not in EDITABLE_FIELDS:
        raise HTTPException(400, f"field '{field_name}' is not editable")
    if field_name in _NUMERIC_FIELDS:
        if new_value is not None:
            try:
                new_value = float(new_value)
            except (TypeError, ValueError):
                raise HTTPException(400, f"'{field_name}' must be numeric")
            if new_value < 0:
                raise HTTPException(400, f"'{field_name}' cannot be negative")
    if field_name == "department" and (new_value is None or not str(new_value).strip()):
        raise HTTPException(400, "department cannot be empty")
    if field_name in IDENTIFIER_FIELDS and not new_value:
        raise HTTPException(400, f"'{field_name}' cannot be cleared")


def apply_correction(repo: Repository, row_id: str, field_name: str, new_value, reason: str | None, source: str = "LOCAL_USER") -> dict:
    row = repo.get_product_row(row_id)
    if not row:
        raise HTTPException(404, "product row not found")

    validate_patch(field_name, new_value)
    if field_name in IDENTIFIER_FIELDS and not reason:
        raise HTTPException(400, "reason is required when correcting an identifier field (barcode/article)")

    column = _FIELD_TO_COLUMN[field_name]
    old_value = row.get(column)
    coerced = float(new_value) if field_name in _NUMERIC_FIELDS and new_value is not None else new_value

    column_updates = {column: coerced}
    review_required, review_reasons = _recompute_review_flags(row, column, coerced)
    column_updates["review_required"] = int(review_required)
    column_updates["review_reasons"] = json.dumps(review_reasons)

    result = repo.update_product_row_field(
        row_id, field_name, old_value, coerced, column_updates, reason, source,
    )
    propagated = 0
    if field_name == "name" and row.get("barcode") and coerced:
        propagated = _propagate_name_correction(repo, row["barcode"], coerced, row_id, row["document_id"], source)
    return {**result, "row": repo.get_product_row(row_id), "propagatedCount": propagated}


def _propagate_name_correction(repo: Repository, barcode: str, corrected_name: str, source_row_id: str, source_document_id: str, source: str) -> int:
    """User request: correcting a product's name should also fix the same
    product's name everywhere else it appears (a different document/bill
    carrying the same barcode), not just the one row being edited - and
    should stick for documents imported later too, via Local Verified
    Master (same barcode-match path resolve_local_master() already uses
    for a brand-new document's rows)."""
    repo.upsert_local_master_name(barcode, corrected_name, source_document_id)

    updated = 0
    for sibling in repo.list_product_rows_by_barcode(barcode, exclude_row_id=source_row_id):
        if sibling.get("resolved_product_name") == corrected_name:
            continue
        sibling_review_required, sibling_review_reasons = _recompute_review_flags(sibling, "resolved_product_name", corrected_name)
        repo.update_product_row_field(
            sibling["id"], "name", sibling.get("resolved_product_name"), corrected_name,
            {
                "resolved_product_name": corrected_name,
                "review_required": int(sibling_review_required),
                "review_reasons": json.dumps(sibling_review_reasons),
            },
            f"auto-applied: barcode {barcode} corrected on another document (row {source_row_id})",
            source,
        )
        updated += 1
    return updated


def _recompute_review_flags(row: dict, changed_column: str, new_value) -> tuple[bool, list[str]]:
    """Amount validation (spec §13): when quantity, unit_price and amount
    are all present, flag AMOUNT_MISMATCH if they don't reconcile; clears
    automatically once corrected values agree, by simply not re-adding the
    flag. Never fabricates the check for a document type that doesn't
    carry these fields (all three None => no mismatch flag possible)."""
    merged = dict(row)
    merged[changed_column] = new_value
    reasons = set(json.loads(row.get("review_reasons") or "[]"))
    reasons.discard("AMOUNT_MISMATCH")

    qty = merged.get("sku_qty") if merged.get("sku_qty") is not None else merged.get("pu_qty")
    unit_price, amount = merged.get("unit_price"), merged.get("amount")
    if qty is not None and unit_price is not None and amount is not None:
        calculated = round(qty * unit_price, 2)
        if abs(calculated - amount) > 0.01:
            reasons.add("AMOUNT_MISMATCH")

    if not merged.get("department") or str(merged["department"]).strip().upper() == "UNKNOWN":
        reasons.add("MISSING_DEPARTMENT")
    else:
        reasons.discard("MISSING_DEPARTMENT")

    return (len(reasons) > 0), sorted(reasons)


def confirm_review_row(repo: Repository, row_id: str, source: str = "LOCAL_USER") -> dict:
    """Bulk-confirm-safe path: only clears review_required when there is no
    identifier conflict / amount mismatch / unknown barcode outstanding -
    those must go through an explicit correction instead."""
    row = repo.get_product_row(row_id)
    if not row:
        raise HTTPException(404, "product row not found")
    reasons = set(json.loads(row.get("review_reasons") or "[]"))
    unsafe = reasons & {"UNKNOWN_BARCODE", "AMOUNT_MISMATCH", "DEPARTMENT_CONFLICT", "INVALID_IDENTIFIER"}
    if unsafe:
        raise HTTPException(409, f"cannot bulk-confirm: unresolved {sorted(unsafe)}")
    repo.update_product_row_field(
        row_id, "review_required", True, False,
        {"review_required": 0, "review_reasons": "[]"}, "confirmed", source,
    )
    return {"confirmed": True, "row": repo.get_product_row(row_id)}
