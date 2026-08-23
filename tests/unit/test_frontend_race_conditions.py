"""Regression guards for a set of race/staleness bugs found during an app
audit and confirmed live via headless Chromium (see PR description for the
before/after repro): a background store update wiping in-progress typing
in the Products search box, refreshAll() firing three full re-renders
instead of batching them, no guard against overlapping refreshAll() calls,
and two debounced-search inputs (Official Master lookup, Local Master
search) whose async responses could apply out of order. These are
source-level tripwires against the mechanism regressing, not a substitute
for the live verification already done.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "app"


def test_products_search_box_survives_an_unrelated_background_render():
    source = (FRONTEND / "views" / "products.js").read_text(encoding="utf-8")
    assert "localSearchText" in source
    # The input's value attribute must come from the locally-tracked text,
    # not directly from store.state.searchQuery (which is what let an
    # unrelated store.set() elsewhere reset the box mid-keystroke).
    assert 'value="${escapeHtml(localSearchText)}"' in source


def test_products_search_box_restores_focus_after_rerender():
    source = (FRONTEND / "views" / "products.js").read_text(encoding="utf-8")
    assert "hadFocus" in source
    assert "setSelectionRange" in source


def test_refresh_all_is_guarded_against_concurrent_callers():
    source = (FRONTEND / "state.js").read_text(encoding="utf-8")
    assert "_refreshAllInFlight" in source
    assert "_refreshAllQueued" in source


def test_refresh_all_batches_division_and_overview_into_one_set_call():
    source = (FRONTEND / "state.js").read_text(encoding="utf-8")
    # refreshAll() used to call this.set() three times (documents/dashboard/
    # products, then divisionSummary, then dashboardOverview independently)
    # - now the latter two are computed together and applied in one set().
    assert "_computeDivisionSummary" in source
    assert "_computeDashboardOverview" in source
    assert "this.set({ divisionSummary, dashboardOverview })" in source


def test_main_render_guards_against_overlapping_async_renders():
    source = (FRONTEND / "main.js").read_text(encoding="utf-8")
    assert "renderGeneration" in source


def test_official_master_lookup_guards_against_out_of_order_responses():
    source = (FRONTEND / "views" / "productMaster.js").read_text(encoding="utf-8")
    assert "myRequestId !== requestId" in source


def test_local_master_search_guards_against_out_of_order_responses():
    source = (FRONTEND / "views" / "productMaster.js").read_text(encoding="utf-8")
    assert "myRequestId !== searchRequestId" in source
