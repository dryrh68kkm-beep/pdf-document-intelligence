"""ValidationEngine for packing_list_bpdc: reconciles per pallet block
(this template's own printed "Total" is per-pallet, not per-department -
a pallet can carry rows from several departments, so there is no
per-department total to check against; see templates/packing_list_bpdc.py).
"""
from __future__ import annotations

from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.models.document import TableRow, ValidationIssue
from pdf_document_intelligence.tables.reconstruct_bpdc import PalletBlock


def reconcile_pallet_block(rows: list[TableRow], block: PalletBlock, settings: Settings) -> list[ValidationIssue]:
    label = block.pallet_no or f"lot:{block.lot_no}"
    issues: list[ValidationIssue] = []
    if block.total is None:
        issues.append(
            ValidationIssue(
                code="TOTAL_ROW_NOT_FOUND",
                message=f"Pallet {label!r} has no Total row to reconcile against",
                severity="warning",
                table=label,
            )
        )
        return issues

    if block.total.line_count is not None and block.total.line_count != len(rows):
        issues.append(
            ValidationIssue(
                code="TOTAL_MISMATCH",
                message=f"Pallet {label}: declared line count {block.total.line_count} != extracted row count {len(rows)}",
                severity="error",
                table=label,
            )
        )

    def summed(field: str) -> float:
        total = 0.0
        for row in rows:
            fv = row.fields.get(field)
            if fv is not None and isinstance(fv.value, (int, float)):
                total += fv.value
        return total

    checks = (
        ("weight_qty", block.total.weight_qty),
        ("pu_qty", block.total.pu_qty),
        ("sku_qty", block.total.sku_qty),
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
                        f"Pallet {label}: declared {field}={declared} but extracted rows sum to "
                        f"{extracted:.3f} (tolerance {settings.reconciliation_abs_tolerance})"
                    ),
                    severity="error",
                    table=label,
                    field=field,
                )
            )
    return issues
