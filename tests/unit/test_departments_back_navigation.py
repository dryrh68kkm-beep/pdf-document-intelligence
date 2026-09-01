"""User report: clicking a department card on the Departments page landed
on Products filtered to that department with no way back to the
Departments summary/totals view - only Products' own "‹ ทุกแผนก" link,
which just cleared the filter and stayed on Products, and the sidebar's
own "Departments" nav item (easy to miss after landing on a filtered
list).

Fix: departments.js's card click now also sets deptFilterFrom:
"departments" in the navigation, and products.js's back-link checks it -
when set, the link reads "‹ กลับไปหน้าแผนก" and navigates back to the
Departments view instead of just clearing the filter. Any other path that
sets deptFilter (the Division select forcing a stale department to clear,
or picking a department directly from Products' own dropdown) explicitly
clears deptFilterFrom so a later, unrelated filter change never silently
inherits "back goes to Departments" from a stale earlier navigation.

Both files are DOM-driving view modules with no pure function to execute
outside a browser, matching this project's established pattern for this
class of coverage (see test_documents_view_pdf.py) - these are
source-level regression guards. Live-verified in a real browser
(Playwright): clicked a Departments card, landed on Products showing
"‹ กลับไปหน้าแผนก", clicked it, and landed back on the Departments view.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEPARTMENTS = ROOT / "frontend" / "app" / "views" / "departments.js"
PRODUCTS = ROOT / "frontend" / "app" / "views" / "products.js"
STATE = ROOT / "frontend" / "app" / "state.js"


def test_department_card_click_tags_the_navigation_origin():
    source = DEPARTMENTS.read_text(encoding="utf-8")
    assert 'deptFilterFrom: "departments"' in source


def test_products_back_link_returns_to_departments_when_tagged():
    source = PRODUCTS.read_text(encoding="utf-8")
    assert '"‹ กลับไปหน้าแผนก"' in source
    assert 'store.navigate("departments")' in source


def test_products_back_link_falls_back_to_clearing_the_filter_otherwise():
    """Regression guard: every other deptFilter source (Dashboard's
    Division table, Products' own dropdowns) must keep the original
    behavior of just clearing the filter and staying on Products - only a
    Departments-card click should navigate away."""
    source = PRODUCTS.read_text(encoding="utf-8")
    assert '"‹ ทุกแผนก"' in source
    handler_start = source.index('#clearDept").addEventListener("click"')
    handler_end = source.index("\n  }", handler_start)
    handler_body = source[handler_start:handler_end]
    assert 'deptFilter: null, deptFilterLabel: null' in handler_body


def test_dropdown_driven_filter_changes_clear_the_stale_origin_flag():
    """Picking a department directly from Products' own dropdown, or
    having the Division select force-clear an invalidated department, must
    not leave a stale deptFilterFrom="departments" around to hijack a
    later, unrelated "back" click into navigating away from Products."""
    source = PRODUCTS.read_text(encoding="utf-8")
    dept_select_start = source.index('#productDeptSelect").addEventListener("change"')
    dept_select_end = source.index("\n  });", dept_select_start)
    assert "deptFilterFrom: null" in source[dept_select_start:dept_select_end]

    division_select_start = source.index('#productDivisionSelect").addEventListener("change"')
    division_select_end = source.index("\n  });", division_select_start)
    assert "deptFilterFrom: null" in source[division_select_start:division_select_end]


def test_state_declares_the_new_field_with_a_null_default():
    source = STATE.read_text(encoding="utf-8")
    assert "deptFilterFrom: null" in source
