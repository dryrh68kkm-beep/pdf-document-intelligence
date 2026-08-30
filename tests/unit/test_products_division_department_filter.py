"""Products view: add a ฝ่าย (Division) filter above the existing แผนก
(Department) one, so a user can narrow by Division first, then pick from
only the Departments under it - previously the แผนก dropdown was one long
flat, ungrouped list of every department (see the reported screenshot).

matchesDeptFilter()/matchesDivisionFilter() are plain, import-free functions
- executed directly via Node for real behavioral coverage, matching this
project's established pattern (see test_dashboard_reconciliation_warning.py).

A real bug was found and fixed while building this: the Division select's
change handler originally called draw() (table/pagination redraw only), so
picking a Division never actually updated the แผนก dropdown's own option
list - only a full renderProducts() rebuild regenerates it, since the
department list is scoped to divisionFilter at render time. Verified live in
a browser: after the fix, selecting "NON FOOD DIVISION" narrows the แผนก
dropdown from all ~25 departments down to just the 4 under it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PRODUCTS = ROOT / "frontend" / "app" / "views" / "products.js"

NODE = shutil.which("node")


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    paren_start = source.index("(", start)
    paren_depth = 0
    i = paren_start
    while True:
        if source[i] == "(":
            paren_depth += 1
        elif source[i] == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
        i += 1
    brace_start = source.index("{", i)
    depth = 0
    i = brace_start
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1


def _run_filters(products, dept_filter, division_filter, department_divisions):
    source = PRODUCTS.read_text(encoding="utf-8")
    dept_fn = _extract_function(source, "matchesDeptFilter")
    div_fn = _extract_function(source, "matchesDivisionFilter")
    script = f"""
{dept_fn}
{div_fn}
const products = {json.dumps(products)};
const deptFilter = {json.dumps(dept_filter)};
const divisionFilter = {json.dumps(division_filter)};
const departmentDivisions = {json.dumps(department_divisions)};
const result = products.filter(
  (p) => matchesDeptFilter(p, deptFilter) && matchesDivisionFilter(p, divisionFilter, departmentDivisions)
);
console.log(JSON.stringify(result.map((p) => p.id)));
"""
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


DEPARTMENT_DIVISIONS = {
    "HOUSEHOLD": {"code": "10", "name": "NON FOOD DIVISION"},
    "HOUSEWARE": {"code": "10", "name": "NON FOOD DIVISION"},
    "LIQUOR": {"code": "20", "name": "FOOD DIVISION"},
    "BAKERY": {"code": "30", "name": "FRESH FOOD DIVISION"},
}

PRODUCTS_FIXTURE = [
    {"id": "a", "department": "HOUSEHOLD"},
    {"id": "b", "department": "HOUSEWARE"},
    {"id": "c", "department": "LIQUOR"},
    {"id": "d", "department": "BAKERY"},
    {"id": "e", "department": "UNKNOWN DEPT"},
]


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_division_all_keeps_every_department():
    ids = _run_filters(PRODUCTS_FIXTURE, None, "all", DEPARTMENT_DIVISIONS)
    assert ids == ["a", "b", "c", "d", "e"]


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_division_filter_scopes_to_its_departments_only():
    ids = _run_filters(PRODUCTS_FIXTURE, None, "10", DEPARTMENT_DIVISIONS)
    assert ids == ["a", "b"]


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_division_filter_excludes_a_department_with_no_known_division():
    """A department absent from the department->division master lookup must
    not silently match every Division filter - it should only ever show up
    under "ทุกฝ่าย"."""
    ids = _run_filters(PRODUCTS_FIXTURE, None, "20", DEPARTMENT_DIVISIONS)
    assert "e" not in ids


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_division_and_department_filters_combine():
    ids = _run_filters(PRODUCTS_FIXTURE, "HOUSEWARE", "10", DEPARTMENT_DIVISIONS)
    assert ids == ["b"]


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_department_filter_from_a_different_division_yields_nothing():
    """A stale แผนก selection left over from a different ฝ่าย must not leak
    rows through - the UI layer clears it, but the filter combination itself
    must also be correct if it doesn't."""
    ids = _run_filters(PRODUCTS_FIXTURE, "LIQUOR", "10", DEPARTMENT_DIVISIONS)
    assert ids == []


def test_division_select_change_triggers_a_full_rebuild_not_just_a_row_redraw():
    """Regression guard: the แผนก dropdown's option list is only rebuilt by
    the full renderProducts() render pass (it's scoped to divisionFilter at
    render time) - calling draw() alone leaves it showing the previous
    Division's departments even though the visible rows did update."""
    source = PRODUCTS.read_text(encoding="utf-8")
    handler_start = source.index('#productDivisionSelect").addEventListener("change"')
    handler_end = source.index("\n  });", handler_start)
    handler_body = source[handler_start:handler_end]
    assert "renderProducts(container, store)" in handler_body
