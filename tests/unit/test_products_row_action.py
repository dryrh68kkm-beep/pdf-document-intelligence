"""PR16 (Products UX): the Products table's "จัดการ" column used to render
a "more options" (moreVertical icon) button on every row with no click
handler wired anywhere - dataTable.js exempted [data-row-action] elements
from the row-click handler (so a real action could use the click without
also opening the detail panel) but no caller ever actually attached one.
The button did nothing when clicked, and its mere presence swallowed the
click that would otherwise have opened the row via onRowClick.

dataTable.js is a small, DOM-driving component with no pure function to
execute directly outside a real browser, so - matching the project's
established pattern for this class of frontend bug - these are
source-level regression guards. Live-verified in a real browser during
development: clicking the action button on a review-required row shows
the resolve confirmation and, on confirm, calls the real
POST /api/review/{rowId}/confirm endpoint end to end.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_TABLE = ROOT / "frontend" / "app" / "components" / "dataTable.js"
PRODUCTS = ROOT / "frontend" / "app" / "views" / "products.js"


def test_data_table_wires_a_click_handler_for_row_action_elements():
    source = DATA_TABLE.read_text(encoding="utf-8")
    assert "onRowAction" in source
    assert 'tr.querySelector("[data-row-action]")' in source
    assert "actionEl?.addEventListener(\"click\"" in source


def test_row_action_click_does_not_also_trigger_row_click():
    """The action button must not both perform its own action AND open the
    detail panel from the same click - dataTable.js's row-level listener
    already early-returns for [data-row-action] targets; the action
    listener itself must also stop propagation defensively."""
    source = DATA_TABLE.read_text(encoding="utf-8")
    assert "e.stopPropagation()" in source


def test_products_view_wires_a_real_action_not_a_dead_button():
    source = PRODUCTS.read_text(encoding="utf-8")
    assert "onRowAction:" in source
    # The action must differ by row state - resolve for a row still
    # needing review, otherwise the same "open detail" the row click does.
    assert 'data-row-action="resolve"' in source
    assert 'data-row-action="view"' in source
    # The actual confirm/API-call logic lives in reviewActions.js (PR17)
    # shared with review.js, not duplicated here.
    assert "confirmMarkResolved" in source


def test_products_view_no_longer_renders_the_dead_more_options_button():
    """Regression guard for the original bug: a plain, unconditional
    "more options" icon with no differentiation and no handler."""
    source = PRODUCTS.read_text(encoding="utf-8")
    assert 'data-row-action="menu"' not in source
