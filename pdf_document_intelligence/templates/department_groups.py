"""Department -> Division rollup for Dashboard display only.

Operational hierarchy/master data is not committed to this repository.
Production can supply the same external CSV used by the product catalog via
``PDF_INTELLIGENCE_MASTER_CATALOG``. Missing master data is safe: departments
remain unmapped rather than being guessed or causing application startup to
fail.
"""
from __future__ import annotations

import csv
import functools
import os
import re
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "master_catalog.csv"
CATALOG_ENV = "PDF_INTELLIGENCE_MASTER_CATALOG"
_LEADING_CODE_RE = re.compile(r"^\d+\s+")


def _configured_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    configured = os.getenv(CATALOG_ENV, "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_PATH


def _strip_code(name: str) -> str:
    return _LEADING_CODE_RE.sub("", name).strip()


def load_department_divisions(path: Path | None = None) -> dict[str, str]:
    path = _configured_path(path)
    if not path.is_file():
        return {}
    mapping: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dept = _strip_code((row.get("DEPARTMENT_NAME") or "").strip())
            division = _strip_code((row.get("DIVISION_NAME") or "").strip())
            if dept and division:
                mapping[dept] = division
    return mapping


@functools.lru_cache(maxsize=1)
def get_default_department_divisions() -> dict[str, str]:
    return load_department_divisions()


def major_department_for(name: str) -> str:
    return get_default_department_divisions().get(name, name)


def _split_code(name: str) -> tuple[str | None, str]:
    match = _LEADING_CODE_RE.match(name)
    if not match:
        return None, name
    return match.group().strip(), name[match.end():].strip()


def load_divisions(path: Path | None = None) -> list[tuple[str, str]]:
    path = _configured_path(path)
    if not path.is_file():
        return []
    seen: dict[str, tuple[str, str]] = {}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = (row.get("DIVISION_NAME") or "").strip()
            if not raw or raw in seen:
                continue
            seen[raw] = _split_code(raw)
    return list(seen.values())


def load_department_to_division_code(path: Path | None = None) -> dict[str, tuple[str, str]]:
    path = _configured_path(path)
    if not path.is_file():
        return {}
    mapping: dict[str, tuple[str, str]] = {}
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
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
    bare = _strip_code((name or "").strip())
    return get_default_department_to_division_code().get(bare)
