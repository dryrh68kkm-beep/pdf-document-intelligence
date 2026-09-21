"""Read-only, offline link to a locally-running expiry-dashboard instance.

expiry-dashboard is a separate app with its own repo and no shared code or
database. When both apps happen to run on the same machine, expiry-dashboard's
Desktop deployment writes its near-expiry export to a fixed local path (see
its own config.ps1 - $LOCAL_DATA_PATH + $SOURCE_FILE_BASENAME, typically
C:\\LP-Tools\\ExpiryApp\\www\\NEARLY_EXPIRED_<store>.csv). This module reads
that file directly off disk on demand - no network call, no copy, nothing
written back to expiry-dashboard's folder - and matches each barcode against
this app's own extracted unit prices to estimate the value of near-expiry
stock. If the path isn't configured, or the file isn't there (expiry-dashboard
not installed on this machine, or hasn't run its own fetch yet), everything
here degrades to "unavailable" rather than raising.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any

EXPIRY_LINK_ENV = "PDF_INTELLIGENCE_EXPIRY_LINK_CSV"
# Same three encodings the master-catalog importer tries, in the same
# order, for the same reason (catalog/snapshot.py CATALOG_ENCODING_CANDIDATES)
# - store exports of this shape have shown up in UTF-8, Windows Thai
# codepage (cp874), and plain ISO-8859-11 in practice.
_ENCODING_CANDIDATES = ("utf-8-sig", "cp874", "iso8859_11")


def configured_source_path() -> Path | None:
    configured = os.environ.get(EXPIRY_LINK_ENV, "").strip()
    return Path(configured).expanduser() if configured else None


def _detect_encoding(raw: bytes) -> str:
    for encoding in _ENCODING_CANDIDATES:
        try:
            raw.decode(encoding)
            return encoding
        except UnicodeDecodeError:
            continue
    return _ENCODING_CANDIDATES[0]


def _clean(value: object) -> str:
    return str(value or "").strip()


def _normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return {(key or "").strip().upper(): value for key, value in row.items() if key is not None}


def read_near_expiry_rows(source_path: Path) -> list[dict[str, str]]:
    """Parse expiry-dashboard's near-expiry export (BAR_CODE, DESCRIPTION,
    STOCK_QTY, DAY_LEFT, SUB_DEPT_NAME, DIV, DEPT). Returns [] if the file
    is missing - callers distinguish "not configured/found" from "found but
    empty" via the file's own existence, not this return value."""
    if not source_path.is_file():
        return []
    raw = source_path.read_bytes()
    encoding = _detect_encoding(raw)
    rows: list[dict[str, str]] = []
    with source_path.open("r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for raw_row in reader:
            row = _normalize_row(raw_row)
            barcode = _clean(row.get("BAR_CODE"))
            if not barcode:
                continue
            rows.append(
                {
                    "barcode": barcode,
                    "description": _clean(row.get("DESCRIPTION")),
                    "stockQty": _clean(row.get("STOCK_QTY")),
                    "dayLeft": _clean(row.get("DAY_LEFT")),
                    "subDeptName": _clean(row.get("SUB_DEPT_NAME")),
                    "div": _clean(row.get("DIV")),
                    "dept": _clean(row.get("DEPT")),
                }
            )
    return rows


def _to_float(value: str) -> float:
    try:
        return float(value) if value else 0.0
    except ValueError:
        return 0.0


def build_summary(source_path: Path | None, price_by_barcode: dict[str, float]) -> dict[str, Any]:
    """Match expiry-dashboard's near-expiry stock against this app's own
    latest extracted unit prices (by barcode) to estimate near-expiry value.
    A barcode with no match here simply isn't priced - it still counts
    toward itemCount but not matchedCount/totalValue, same "never hide a
    gap, report it" approach as the Dashboard's own reconciliation warnings."""
    if source_path is None:
        return {
            "configured": False, "available": False, "fileFound": False,
            "itemCount": 0, "matchedCount": 0, "unmatchedCount": 0, "totalValue": 0.0,
        }
    if not source_path.is_file():
        return {
            "configured": True, "available": False, "fileFound": False,
            "itemCount": 0, "matchedCount": 0, "unmatchedCount": 0, "totalValue": 0.0,
        }

    rows = read_near_expiry_rows(source_path)
    matched = 0
    total_value = 0.0
    for row in rows:
        price = price_by_barcode.get(row["barcode"])
        if price is None:
            continue
        matched += 1
        total_value += _to_float(row["stockQty"]) * price

    return {
        "configured": True,
        "available": True,
        "fileFound": True,
        "itemCount": len(rows),
        "matchedCount": matched,
        "unmatchedCount": len(rows) - matched,
        "totalValue": round(total_value, 2),
    }
