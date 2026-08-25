"""Master product catalog backed by a private one-time local snapshot.

Production supplies the external CSV only for the initial import. Selected
fields are compiled into PDF_INTELLIGENCE_DATA_DIR and all later reads use the
snapshot, so the source master file does not need to remain beside the app and
is never committed to the repository.
"""
from __future__ import annotations

import functools
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pdf_document_intelligence.catalog.snapshot import (
    import_catalog_snapshot,
    load_catalog_snapshot,
)


def _parse_unit_cost(raw: object) -> Decimal | None:
    text = str(raw or "").strip()
    if not text:
        return None
    # Real exports have shown thousands separators and a currency symbol
    # in this column (e.g. "1,234.50", "฿1,234.50") - strip them rather
    # than dropping the whole cost to None just because a bare Decimal()
    # parse doesn't accept them.
    text = text.replace(",", "").replace("฿", "").strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


class CatalogEntry:
    __slots__ = ("barcode", "name", "structure", "root_code", "unit_cost")

    def __init__(
        self, barcode: str, name: str, structure: str, root_code: str, unit_cost: Decimal | None = None
    ) -> None:
        self.barcode = barcode
        self.name = name
        self.structure = structure
        self.root_code = root_code
        self.unit_cost = unit_cost


def _catalog_from_snapshot() -> dict[str, CatalogEntry]:
    payload = load_catalog_snapshot()
    catalog: dict[str, CatalogEntry] = {}
    for row in payload.get("products", []):
        if not isinstance(row, dict):
            continue
        barcode = str(row.get("barcode") or "").strip()
        name = str(row.get("name") or "").strip()
        if not barcode or not name:
            continue
        catalog[barcode] = CatalogEntry(
            barcode=barcode,
            name=name,
            structure=str(row.get("structure") or "").strip(),
            root_code=str(row.get("root_code") or "").strip(),
            unit_cost=_parse_unit_cost(row.get("unit_cost")),
        )
    return catalog


def load_catalog(path: Path | None = None) -> dict[str, CatalogEntry]:
    """Load catalog data from the internal snapshot.

    Passing ``path`` performs a one-time import from that external source when
    the private snapshot does not yet exist. Existing snapshots are preserved.
    """
    if path is not None:
        import_catalog_snapshot(Path(path))
    return _catalog_from_snapshot()


@functools.lru_cache(maxsize=1)
def get_default_catalog() -> dict[str, CatalogEntry]:
    return load_catalog()
