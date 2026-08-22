"""Master product catalog: barcode -> authoritative product name.

Sensitive operational master data is intentionally NOT stored in this
repository. Production users may point the app at an external local file via
``PDF_INTELLIGENCE_MASTER_CATALOG``. If no external catalog is configured (or
it is unavailable), the application keeps working with an empty catalog and
falls back to PDF/OCR evidence; it must never guess product names.
"""
from __future__ import annotations

import csv
import functools
import os
from pathlib import Path

# Kept only as a backwards-compatible local development location. The path is
# gitignored and must never contain tracked production/company data.
DEFAULT_CATALOG_PATH = Path(__file__).parent.parent.parent / "data" / "master_catalog.csv"
CATALOG_ENV = "PDF_INTELLIGENCE_MASTER_CATALOG"
CATALOG_ENCODING = "utf-8"


class CatalogEntry:
    __slots__ = ("barcode", "name", "structure", "root_code")

    def __init__(self, barcode: str, name: str, structure: str, root_code: str) -> None:
        self.barcode = barcode
        self.name = name
        self.structure = structure
        self.root_code = root_code


def _configured_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    configured = os.getenv(CATALOG_ENV, "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_CATALOG_PATH


def load_catalog(path: Path | None = None) -> dict[str, CatalogEntry]:
    """Load an external catalog when available.

    Missing master data is a supported, safe state: return an empty mapping so
    callers fall back to OCR/PDF evidence and human review rather than failing
    startup or silently inventing values.
    """
    path = _configured_path(path)
    if not path.is_file():
        return {}

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
    return load_catalog()
