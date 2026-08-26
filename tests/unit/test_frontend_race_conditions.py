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


def test_render_passes_a_staleness_check_to_the_view():
    # renderProductMaster is the one view whose own render function does
    # real async work (api.masterSnapshotStatus/listLocalMaster) before its
    # first DOM write - every other view's data is already loaded by the
    # time main.js calls it. Without an ownership token passed through,
    # that fetch resolving after the user has navigated away (or after a
    # second, newer render() of the same view started - a background poll
    # re-invokes render() for whatever view is current) would overwrite
    # #workspace out from under whatever is actually on screen.
    source = (FRONTEND / "main.js").read_text(encoding="utf-8")
    assert "const isStale = () => myGeneration !== renderGeneration;" in source
    assert "await renderView(workspaceEl, store, isStale);" in source


def test_product_master_bails_out_before_its_first_post_fetch_dom_write_if_stale():
    source = (FRONTEND / "views" / "productMaster.js").read_text(encoding="utf-8")
    fn_idx = source.index("export async function renderProductMaster(container, store, isStale)")
    assert fn_idx != -1
    body = source[fn_idx:]
    # The check must land right after the Promise.all fetch and before any
    # of the three branches (no snapshot / empty snapshot / has data) that
    # follow it write to container.innerHTML.
    fetch_idx = body.index("api.listLocalMaster()")
    stale_check_idx = body.index("if (isStale && isStale()) return;")
    # The loading skeleton written before the fetch also uses
    # container.innerHTML - find the *next* write after the stale check,
    # not that first one.
    first_branch_write_idx = body.index("container.innerHTML", stale_check_idx)
    assert fetch_idx < stale_check_idx < first_branch_write_idx


def test_product_master_import_recursive_rerender_checks_staleness_first():
    # The CSV-import success handler recursively re-invokes
    # renderProductMaster() directly against #workspace, bypassing main.js's
    # render() entirely - a second place a slow async op (the upload) can
    # resolve after the user has navigated away and overwrite the wrong view.
    source = (FRONTEND / "views" / "productMaster.js").read_text(encoding="utf-8")
    fn_idx = source.index("function renderImportControl(container, store, isStale)")
    body = source[fn_idx : source.index("function renderLookupControl")]
    upload_idx = body.index("await api.importMasterCatalog(file);")
    stale_check_idx = body.index("if (isStale && isStale()) return;")
    recurse_idx = body.index('await renderProductMaster(document.getElementById("workspace"), store, isStale);')
    assert upload_idx < stale_check_idx < recurse_idx
