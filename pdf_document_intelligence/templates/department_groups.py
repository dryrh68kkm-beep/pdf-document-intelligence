"""Department -> Division rollup for the Dashboard/Departments views,
display-only (never touches extraction, reconciliation, row data, or
export). Backed by the full store division/department/class master
hierarchy the user supplied (data/department_hierarchy.csv, ~30k rows:
DIVISION_NAME, DEPT_GROUP_NAME, DEPARTMENT_NAME, SUBDEPARTMENT_NAME,
CLASS_NAME, SUBCLASS_NAME, ART_SV_NAME) - the DEPARTMENT_NAME ->
DIVISION_NAME rollup used here is a distinct-pair projection of that
file, verified 1:1 (no department name maps to more than one division)
and verified to cover every one of the BPDC sample's 23 extracted
department names exactly (case and spelling, including the truncated
"HOME IMPROVEMEN" and the "_SME" suffix variants) - not an inferred or
guessed grouping. A department name this table doesn't cover (a future
document's department the user hasn't supplied master data for) is left
as its own major department rather than guessed - never a fuzzy/partial
match.
"""
from __future__ import annotations

import csv
import functools
import re
from pathlib import Path

DEFAULT_PATH = Path(__file__).parent.parent.parent / "data" / "department_hierarchy.csv"
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
