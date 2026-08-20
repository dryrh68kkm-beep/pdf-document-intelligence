"""ValidationEngine: department-level reconciliation.

This document type reconciles per department, not with a single
document-wide grand total (each department prints its own "Total" line
count + weight/PU/SKU sums, per §27/§18 of the spec, adapted to what this
real sample actually does). Sum(extracted rows) vs. declared Total, within
a configurable tolerance for float rounding (§25).
"""
from __future__ import annotations

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.models.document import ExtractedTable, ValidationIssue
from pdf_document_intelligence.tables.reconstruct import RawTable


def reconcile_table(table: ExtractedTable, raw: RawTable, settings: Settings) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if raw.total is None:
        issues.append(
            ValidationIssue(
                code="TOTAL_ROW_NOT_FOUND",
                message=f"Department {raw.department!r} has no Total row to reconcile against",
                severity="warning",
                table=table.name,
            )
        )
        return issues

    if raw.total.line_count is not None and raw.total.line_count != len(table.rows):
        issues.append(
            ValidationIssue(
                code="TOTAL_MISMATCH",
                message=(
                    f"{raw.department}: declared line count {raw.total.line_count} "
                    f"!= extracted row count {len(table.rows)}"
                ),
                severity="error",
                table=table.name,
            )
        )

    def summed(field: str) -> float:
        total = 0.0
        for row in table.rows:
            fv = row.fields.get(field)
            if fv is not None and isinstance(fv.value, (int, float)):
                total += fv.value
        return total

    checks = (
        ("weight_qty", raw.total.weight_qty),
        ("pu_qty", raw.total.pu_qty),
        ("sku_qty", raw.total.sku_qty),
    )
    for field, declared in checks:
        if declared is None:
            continue
        extracted = summed(field)
        if abs(extracted - declared) > settings.reconciliation_abs_tolerance:
            issues.append(
                ValidationIssue(
                    code="CALCULATION_MISMATCH",
                    message=(
                        f"{raw.department}: declared {field}={declared} but extracted rows sum to "
                        f"{extracted:.3f} (tolerance {settings.reconciliation_abs_tolerance})"
                    ),
                    severity="error",
                    table=table.name,
                    field=field,
                )
            )

    return issues


def check_duplicate_rows(table: ExtractedTable) -> list[ValidationIssue]:
    """Cross-row duplicate detection (§26): same DN/line/article/barcode
    appearing twice within one department table."""
    seen: dict[tuple, int] = {}
    issues: list[ValidationIssue] = []
    for row in table.rows:
        key = tuple(
            row.fields[f].value if f in row.fields else None
            for f in ("dn_no", "line", "article", "barcode")
        )
        if key in seen:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_ROW",
                    # Deliberately "warning", not "error": verified against the
                    # BPDC golden sample, a dn/line/article/barcode match can be
                    # a real, separately-quantified line item the source
                    # document legitimately lists twice (confirmed by that
                    # document's own declared Total reconciling with both rows
                    # counted) - not always an extraction double-count. A human
                    # can still see it in validation warnings; it must not by
                    # itself force MANUAL_REVIEW_REQUIRED on an otherwise
                    # correct, fully-reconciled document.
                    message=f"Row {row.row_index} duplicates row {seen[key]} (dn/line/article/barcode)",
                    severity="warning",
                    table=table.name,
                    row_index=row.row_index,
                )
            )
        else:
            seen[key] = row.row_index
    return issues
