"""Department -> Division rollup backed by the private master snapshot.

The external master CSV is needed only for first import. Runtime reads the
compiled snapshot from the app data directory and never depends on a tracked
master file in the repository.
"""
from __future__ import annotations

import functools
import re
from pathlib import Path

from pdf_document_intelligence.catalog.snapshot import (
    import_catalog_snapshot,
    load_catalog_snapshot,
)

_LEADING_CODE_RE = re.compile(r"^\d+\s+")


def _strip_code(name: str) -> str:
    return _LEADING_CODE_RE.sub("", name).strip()


def _hierarchy_from_snapshot(path: Path | None = None) -> dict[str, str]:
    if path is not None:
        import_catalog_snapshot(Path(path))
    raw = load_catalog_snapshot().get("department_divisions", {})
    if not isinstance(raw, dict):
        return {}
    mapping: dict[str, str] = {}
    for department, division in raw.items():
        dept = _strip_code(str(department or "").strip())
        div = _strip_code(str(division or "").strip())
        if dept and div:
            mapping[dept] = div
    return mapping


def load_department_divisions(path: Path | None = None) -> dict[str, str]:
    return _hierarchy_from_snapshot(path)


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


def _raw_hierarchy(path: Path | None = None) -> dict[str, str]:
    if path is not None:
        import_catalog_snapshot(Path(path))
    raw = load_catalog_snapshot().get("department_divisions", {})
    if not isinstance(raw, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in raw.items() if str(k).strip() and str(v).strip()}


def load_divisions(path: Path | None = None) -> list[tuple[str, str]]:
    seen: dict[str, tuple[str | None, str]] = {}
    for raw in _raw_hierarchy(path).values():
        if raw not in seen:
            seen[raw] = _split_code(raw)
    return list(seen.values())


def load_department_to_division_code(path: Path | None = None) -> dict[str, tuple[str | None, str]]:
    mapping: dict[str, tuple[str | None, str]] = {}
    for department, division_raw in _raw_hierarchy(path).items():
        dept = _strip_code(department)
        if dept:
            mapping[dept] = _split_code(division_raw)
    return mapping


@functools.lru_cache(maxsize=1)
def get_default_divisions() -> list[tuple[str, str]]:
    return load_divisions()


@functools.lru_cache(maxsize=1)
def get_default_department_to_division_code() -> dict[str, tuple[str | None, str]]:
    return load_department_to_division_code()


def division_for_department(name: str) -> tuple[str | None, str] | None:
    bare = _strip_code((name or "").strip())
    return get_default_department_to_division_code().get(bare)
