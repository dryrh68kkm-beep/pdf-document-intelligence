"""One-time import of external master data into the app's private data directory.

The source CSV is never copied into the repository. On first use, selected
fields are compiled into a local JSON snapshot under PDF_INTELLIGENCE_DATA_DIR.
Subsequent runs use that snapshot and no longer require the source CSV.
"""
from __future__ import annotations

import csv
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pdf_document_intelligence.db.paths import get_data_dir

CATALOG_ENV = "PDF_INTELLIGENCE_MASTER_CATALOG"
SNAPSHOT_FILENAME = "master_catalog.snapshot.json"
SNAPSHOT_VERSION = 1
# Real store master exports have shown up in both UTF-8 and the Windows Thai
# codepage (cp874, aka iso8859_11/TIS-620) - decoding a cp874 file as UTF-8
# with errors="replace" doesn't raise, it silently turns every Thai
# character into U+FFFD and produces mojibake product names throughout the
# catalog (seen in practice after an in-web CSV re-import). Try encodings in
# order and keep the first one that decodes the whole file cleanly.
CATALOG_ENCODING_CANDIDATES = ("utf-8-sig", "cp874")


def get_snapshot_path() -> Path:
    return get_data_dir() / SNAPSHOT_FILENAME


def configured_source_path() -> Path | None:
    configured = os.getenv(CATALOG_ENV, "").strip()
    return Path(configured).expanduser() if configured else None


def _clean(value: object) -> str:
    return str(value or "").strip()


def _detect_encoding(source_path: Path) -> str:
    raw = source_path.read_bytes()
    for encoding in CATALOG_ENCODING_CANDIDATES:
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    # Nothing decoded cleanly - fall back to the first candidate with
    # replacement rather than raising, so an unusual file still imports
    # (possibly with a handful of garbled characters) instead of blocking
    # the whole catalog import outright.
    return CATALOG_ENCODING_CANDIDATES[0]


def _compile_source(source_path: Path) -> dict[str, Any]:
    products: list[dict[str, str]] = []
    hierarchy: dict[str, str] = {}

    encoding = _detect_encoding(source_path)
    with source_path.open("r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            barcode = _clean(row.get("BARCODE"))
            name = _clean(row.get("ART_SV_NAME"))
            if barcode and name:
                products.append(
                    {
                        "barcode": barcode,
                        "name": name,
                        "structure": _clean(row.get("SUBCLASS_NAME")),
                        "root_code": _clean(row.get("ART_NO")),
                    }
                )

            department = _clean(row.get("DEPARTMENT_NAME"))
            division = _clean(row.get("DIVISION_NAME"))
            if department and division:
                hierarchy[department] = division

    return {
        "version": SNAPSHOT_VERSION,
        "products": products,
        "department_divisions": hierarchy,
    }


def import_catalog_snapshot(
    source_path: Path,
    *,
    snapshot_path: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Compile an external CSV into a private local snapshot.

    By default an existing snapshot is left untouched, making the operation a
    true one-time import. Pass ``overwrite=True`` only for an intentional
    master refresh.
    """
    source_path = Path(source_path).expanduser()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)

    target = snapshot_path or get_snapshot_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        return target

    payload = _compile_source(source_path)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
            f.flush()
            os.fsync(f.fileno())
        Path(temp_name).replace(target)
    except Exception:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return target


def ensure_catalog_snapshot() -> Path | None:
    """Return the local snapshot, importing the configured source once if needed."""
    target = get_snapshot_path()
    if target.is_file():
        return target

    source = configured_source_path()
    if source is None or not source.is_file():
        return None
    return import_catalog_snapshot(source, snapshot_path=target)


def load_catalog_snapshot() -> dict[str, Any]:
    path = ensure_catalog_snapshot()
    if path is None:
        return {"version": SNAPSHOT_VERSION, "products": [], "department_divisions": {}}

    try:
        with path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"version": SNAPSHOT_VERSION, "products": [], "department_divisions": {}}

    if not isinstance(payload, dict) or payload.get("version") != SNAPSHOT_VERSION:
        return {"version": SNAPSHOT_VERSION, "products": [], "department_divisions": {}}
    return payload
