"""Cross-program reference data for accuracy checks - no manual input.

Besides its own Official/Local Master, the PDF pipeline can check what it
read against independent records the store's other programs already hold:

  * Stock Atlas stock-count database (barcode -> product name, ~20k items)
  * Stock Atlas OOS reports            (barcode -> product name)
  * expiry-dashboard daily export      (see expiry_dashboard_lookup.py)

Two uses (wired in api/rows.py):
  1. name resolution - an exact barcode hit gives the name without OCR;
  2. barcode repair  - a barcode that matches nothing and fails the GTIN
     check digit is compared with every known barcode one edit away
     (substituted / transposed / dropped / extra digit). It is replaced
     only when exactly ONE check-digit-valid known barcode is a neighbour;
     the original reading stays in the field's `raw_value`.

Files are given as os.pathsep-separated lists (first existing wins) via
PDI_CROSS_REFERENCE_COUNT_FILES / PDI_CROSS_REFERENCE_OOS_FILES, so the app
still runs fine standalone (no files = no extra evidence).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import unicodedata
from pathlib import Path

GTIN_LENGTHS = (8, 12, 13, 14)

_cache: dict[tuple, dict[str, str]] = {}


def gtin_valid(code: str) -> bool:
    """GS1 mod-10 check digit for GTIN-8/12/13/14."""
    if not code.isdigit() or len(code) not in GTIN_LENGTHS:
        return False
    total = sum(int(c) * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(code[:-1])))
    return (10 - total % 10) % 10 == int(code[-1])


def _first_existing(spec: str) -> Path | None:
    for part in (spec or "").split(os.pathsep):
        part = part.strip()
        if part and Path(part).is_file():
            return Path(part)
    return None


def _clean_barcode(v: object) -> str:
    s = str(v if v is not None else "").strip()
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


def _read_count_names(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    out: dict[str, str] = {}
    for p in data.get("products") or []:
        if isinstance(p, (list, tuple)) and len(p) >= 3 and p[0] and p[2]:
            out[_clean_barcode(p[0])] = str(p[2]).strip()
    return out


def _read_oos_names(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    out: dict[str, str] = {}
    for it in data.get("items") or []:
        if isinstance(it, dict) and it.get("barcode") and it.get("name"):
            out[_clean_barcode(it["barcode"])] = str(it["name"]).strip()
    return out


def _load(spec: str, reader) -> dict[str, str]:
    path = _first_existing(spec)
    if path is None:
        return {}
    try:
        st = path.stat()
    except OSError:
        return {}
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key not in _cache:
        for k in [k for k in _cache if k[0] == key[0]]:
            del _cache[k]
        try:
            _cache[key] = reader(path)
        except (OSError, ValueError):
            _cache[key] = {}
    return _cache[key]


def reference_name(barcode: str, settings) -> tuple[str, str] | None:
    """(name, source) from the other programs' data, or None."""
    name = _load(settings.cross_reference_count_files, _read_count_names).get(barcode)
    if name:
        return name, "STOCK_ATLAS_COUNT"
    name = _load(settings.cross_reference_oos_files, _read_oos_names).get(barcode)
    if name:
        return name, "STOCK_ATLAS_OOS"
    return None


def neighbors(code: str) -> set[str]:
    """Every digit string one edit away from `code`, restricted to real GTIN lengths."""
    out: set[str] = set()
    n = len(code)
    for i in range(n):
        for d in "0123456789":
            if d != code[i]:
                out.add(code[:i] + d + code[i + 1:])
    for i in range(n - 1):
        if code[i] != code[i + 1]:
            out.add(code[:i] + code[i + 1] + code[i] + code[i + 2:])
    for i in range(n):
        out.add(code[:i] + code[i + 1:])
    for i in range(n + 1):
        for d in "0123456789":
            out.add(code[:i] + d + code[i:])
    out.discard(code)
    return {c for c in out if len(c) in GTIN_LENGTHS}


def _norm(text: object) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")).casefold())


def name_similarity(a: object, b: object) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()
