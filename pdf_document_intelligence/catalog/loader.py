"""Master product catalog backed by a private one-time local snapshot.

Production supplies the external CSV only for the initial import. Selected
fields are compiled into PDF_INTELLIGENCE_DATA_DIR and all later reads use the
snapshot, so the source master file does not need to remain beside the app and
is never committed to the repository.
"""
from __future__ import annotations

import functools
from pathlib import Path

from pdf_document_intelligence.catalog.snapshot import (
    import_catalog_snapshot,
    load_catalog_snapshot,
)


class CatalogEntry:
    __slots__ = ("barcode", "name", "structure", "root_code")

    def __init__(self, barcode: str, name: str, structure: str, root_code: str) -> None:
        self.barcode = barcode
        self.name = name
        self.structure = structure
        self.root_code = root_code


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
