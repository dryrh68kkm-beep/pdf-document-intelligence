"""Master product catalog: barcode -> authoritative product name.

This is the highest-confidence source of truth available for the `name`
field — better than OCR, because it's an exact lookup against real master
data instead of pixel-reading a possibly-defective PDF. Per the
evidence-first principle, a catalog match is treated as ground truth
(confidence 1.0, not flagged for review); a barcode with no catalog entry
falls back to whatever text-layer/OCR reading the pipeline already has —
never guessed from the catalog (e.g. fuzzy-matching a similar name).
"""
from __future__ import annotations

import csv
import functools
from pathlib import Path

DEFAULT_CATALOG_PATH = Path(__file__).parent.parent.parent / "data" / "master_catalog.csv"
# The unified master file (also the Division rollup's source - see
# templates/department_groups.py) is stored UTF-8 in this repo, converted
# once from the source export's iso8859_11 (Thai) encoding on ingestion.
CATALOG_ENCODING = "utf-8"


class CatalogEntry:
    __slots__ = ("barcode", "name", "structure", "root_code")

    def __init__(self, barcode: str, name: str, structure: str, root_code: str) -> None:
        self.barcode = barcode
        self.name = name
        self.structure = structure
        self.root_code = root_code


def load_catalog(path: Path | None = None) -> dict[str, CatalogEntry]:
    path = path or DEFAULT_CATALOG_PATH
    catalog: dict[str, CatalogEntry] = {}
    with path.open("r", encoding=CATALOG_ENCODING, errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            barcode = (row.get("BARCODE") or "").strip()
            name = (row.get("ART_SV_NAME") or "").strip()
            if not barcode or not name:
                continue
            catalog[barcode] = CatalogEntry(
                barcode=barcode,
                name=name,
                structure=(row.get("SUBCLASS_NAME") or "").strip(),
                root_code=(row.get("ART_NO") or "").strip(),
            )
    return catalog


@functools.lru_cache(maxsize=1)
def get_default_catalog() -> dict[str, CatalogEntry]:
    """Cached singleton: the catalog is ~35k rows and doesn't change during
    a process lifetime, so load it once."""
    return load_catalog()
