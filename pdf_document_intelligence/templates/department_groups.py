"""Department -> Division rollup for the Dashboard/Departments views,
display-only (never touches extraction, reconciliation, row data, or
export). Backed by the same unified store master file the barcode
catalog uses (data/master_catalog.csv, catalog/loader.py) - ~30k rows
including DIVISION_NAME, DEPT_GROUP_NAME, DEPARTMENT_NAME,
SUBDEPARTMENT_NAME, CLASS_NAME, SUBCLASS_NAME, ART_SV_NAME alongside the
barcode/name columns - the DEPARTMENT_NAME -> DIVISION_NAME rollup used
here is a distinct-pair projection of that file, verified 1:1 (no
department name maps to more than one division) and verified to cover
every one of the BPDC sample's 23 extracted department names exactly
(case and spelling, including the truncated "HOME IMPROVEMEN" and the
"_SME" suffix variants) - not an inferred or guessed grouping. A
department name this table doesn't cover (a future document's department
the user hasn't supplied master data for) is left as its own major
department rather than guessed - never a fuzzy/partial match.
"""
from __future__ import annotations

import csv
import functools
import re
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "master_catalog.csv"
_LEADING_CODE_RE = re.compile(r"^\d+\s+")


def _strip_code(name: str) -> str:
    return _LEADING_CODE_RE.sub("", name).strip()


def load_department_divisions(path: Path | None = None) -> dict[str, str]:
    """Maps a bare department name (as extracted from a document, no
    leading numeric code) to its bare division name."""
    path = path or DEFAULT_PATH
    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = _strip_code((row.get("DEPARTMENT_NAME") or "").strip())
            division = _strip_code((row.get("DIVISION_NAME") or "").strip())
            if dept and division:
                mapping[dept] = division
    return mapping


@functools.lru_cache(maxsize=1)
def get_default_department_divisions() -> dict[str, str]:
    """Cached singleton: the hierarchy file is ~30k rows and doesn't
    change during a process lifetime, so load it once."""
    return load_department_divisions()


def major_department_for(name: str) -> str:
    return get_default_department_divisions().get(name, name)


def _split_code(name: str) -> tuple[str | None, str]:
    """Splits a hierarchy-file name like "04 DRY FOOD" into its leading
    numeric code ("04") and bare name ("DRY FOOD"). Returns (None, name)
    if the name carries no leading code (shouldn't happen for a
    DIVISION_NAME in the real master file, but keeps this total)."""
    match = _LEADING_CODE_RE.match(name)
    if not match:
        return None, name
    return match.group().strip(), name[match.end():].strip()


def load_divisions(path: Path | None = None) -> list[tuple[str, str]]:
    """The Dashboard's source of truth for "the 6 divisions": a
    distinct-value projection of DIVISION_NAME from data/master_catalog.csv,
    in the order first encountered, as (code, bare_name) pairs - e.g.
    ("04", "DRY FOOD"). Never hand-typed; this file always drives it."""
    path = path or DEFAULT_PATH
    seen: dict[str, tuple[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = (row.get("DIVISION_NAME") or "").strip()
            if not raw or raw in seen:
                continue
            seen[raw] = _split_code(raw)
    return list(seen.values())


def load_department_to_division_code(path: Path | None = None) -> dict[str, tuple[str, str]]:
    """Maps a bare department name (leading numeric code stripped, as
    extracted from a document) to its (division_code, division_bare_name)
    pair. A department this table doesn't cover is simply absent from the
    dict - callers must treat that as UNMAPPED, never guess a division for
    it and never mint a new one."""
    path = path or DEFAULT_PATH
    mapping: dict[str, tuple[str, str]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = _strip_code((row.get("DEPARTMENT_NAME") or "").strip())
            division_raw = (row.get("DIVISION_NAME") or "").strip()
            if not dept or not division_raw:
                continue
            mapping[dept] = _split_code(division_raw)
    return mapping


@functools.lru_cache(maxsize=1)
def get_default_divisions() -> list[tuple[str, str]]:
    return load_divisions()


@functools.lru_cache(maxsize=1)
def get_default_department_to_division_code() -> dict[str, tuple[str, str]]:
    return load_department_to_division_code()


def division_for_department(name: str) -> tuple[str, str] | None:
    """(division_code, division_bare_name) for a bare department name, or
    None if it can't be mapped through data/master_catalog.csv - the
    UNMAPPED case (rule: never invent a 7th division for it)."""
    bare = _strip_code((name or "").strip())
    return get_default_department_to_division_code().get(bare)
