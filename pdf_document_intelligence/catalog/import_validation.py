"""Validation for a *user-driven* master catalog import (the Product
Master page's CSV upload / POST /api/master/import) - deliberately kept
separate from catalog/snapshot.py's import_catalog_snapshot(), which stays
a permissive, general-purpose "compile this CSV into a snapshot" primitive
also used to import hierarchy-only reference data (department->division
mappings with no barcode/product rows at all - the pattern the whole test
suite's own synthetic fixtures rely on via ensure_catalog_snapshot()).
Bolting a "must have product rows" rule onto that shared primitive would
have broken every one of those legitimate hierarchy-only imports; this
module's checks apply only to the product-master-specific HTTP endpoint,
which is unambiguously about barcode/product data.
"""
from __future__ import annotations

from typing import Any

# A new import with far fewer product rows than the catalog it would
# replace is a strong signal of a wrong/partial/corrupt file (a truncated
# export, an unrelated CSV with the right column names but almost no data,
# ...) rather than a deliberate, much smaller catalog - refusing it
# outright protects the much larger existing catalog every other feature
# (name resolution, unit pricing, division rollups) already depends on.
# Deliberately not e.g. 0.5: a genuinely smaller intentional re-import (a
# store trimming its own catalog) is far more plausible than losing over
# 90% of rows by accident, so only the extreme case is treated as fatal.
MIN_CREDIBLE_ROW_RATIO = 0.1


class MasterImportError(Exception):
    """A newly-imported master catalog failed validation - the caller
    (api/app.py's import endpoint) is responsible for restoring whatever
    snapshot existed before the import that produced this payload."""

    pass


def validate_payload(payload: dict[str, Any], previous_payload: dict[str, Any] | None) -> list[str]:
    """Raises MasterImportError for anything fatal enough to refuse the
    import outright; returns a list of non-fatal warning strings
    otherwise (surfaced in the API response, import still stands)."""
    products = payload.get("products", [])
    if not products:
        raise MasterImportError(
            "No usable product rows found. Every row needs both a BARCODE and an ART_SV_NAME "
            "(product name) column with data - check the file's headers and content."
        )

    if previous_payload is not None:
        previous_count = len(previous_payload.get("products") or [])
        if previous_count > 0 and len(products) < previous_count * MIN_CREDIBLE_ROW_RATIO:
            raise MasterImportError(
                f"New file has only {len(products)} usable product rows, far fewer than the "
                f"current catalog's {previous_count} - refusing to import in case this is a "
                "partial or wrong file. If this is intentional, confirm the file is complete "
                "and correct, then re-import."
            )

    warnings: list[str] = []

    barcodes = [p["barcode"] for p in products]
    distinct = len(set(barcodes))
    if distinct < len(barcodes) * 0.5:
        warnings.append(
            f"Only {distinct} distinct barcodes across {len(barcodes)} product rows - "
            "check the file for duplicate or misaligned rows."
        )

    with_cost = sum(1 for p in products if p.get("unit_cost"))
    if with_cost == 0:
        warnings.append("No CURRENT_COST values found - unit prices will be unavailable for every product.")
    elif with_cost < len(products) * 0.5:
        warnings.append(
            f"Only {with_cost} of {len(products)} product rows have a parseable CURRENT_COST - "
            "unit prices will be missing for the rest."
        )

    return warnings
