"""User request: add a per-document drill-down alongside the Dashboard's
existing date-range and Division filters, so "มูลค่าตาม Division" (and the
rest of the Dashboard: KPI cards, product list, department chart) can be
narrowed to one specific document instead of always summing every document
in the selected date range.

state.js's Store methods (_computeDashboardOverview, setDashboardOverviewFilters)
and dashboard.js's renderDashboard are not pure functions (they close over
`this.state`/the DOM), so these are source-level regression guards matching
this project's established pattern for that bug class (see
test_documents_reprocess_all.py, test_division_summary_404_pruning.py).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "frontend" / "app" / "state.js"
DASHBOARD = ROOT / "frontend" / "app" / "views" / "dashboard.js"


def _state_source() -> str:
    return STATE.read_text(encoding="utf-8")


def _dashboard_source() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_dashboard_document_filter_defaults_to_all_in_initial_state():
    source = _state_source()
    assert 'dashboardDocumentFilter: "all"' in source


def test_compute_dashboard_overview_scopes_in_range_to_the_selected_document():
    source = _state_source()
    start = source.index("async _computeDashboardOverview(")
    end = source.index("\n  }\n\n  async refreshDashboardOverview", start)
    body = source[start:end]
    assert "dashboardDocumentFilter" in body
    assert 'doc.id === dashboardDocumentFilter' in body
    # "all" (and "" for an unset/legacy value) must behave as unfiltered -
    # every existing caller that never passes a documentId must keep
    # summing the whole date range exactly as before this filter existed.
    assert 'dashboardDocumentFilter === "all"' in body
    assert 'dashboardDocumentFilter === ""' in body


def test_set_dashboard_overview_filters_accepts_and_applies_document_id():
    source = _state_source()
    start = source.index("async setDashboardOverviewFilters(")
    end = source.index("\n  }", start)
    body = source[start:end]
    assert "documentId" in body
    assert "dashboardDocumentFilter: documentId ?? this.state.dashboardDocumentFilter" in body


def test_dashboard_document_select_is_wired_and_scoped_to_the_current_date_range():
    source = _dashboard_source()
    assert 'id="dashDocumentSelect"' in source
    assert '#dashDocumentSelect' in source
    handler_line = next(line for line in source.splitlines() if "#dashDocumentSelect" in line and "addEventListener" in line)
    assert "refetch({ documentId: e.target.value })" in handler_line

    options_start = source.index("const documentFilterOptions =")
    options_end = source.index(";\n", options_start)
    options_block = source[options_start:options_end]
    # Options must be scoped to completed documents in the currently
    # selected date range, not every document ever uploaded - a document
    # outside the range wouldn't contribute to the overview anyway.
    assert 'doc.status === "complete"' in options_block
    assert "inRange(doc.documentDate, dashboardDateFrom, dashboardDateTo)" in options_block


def test_product_list_filtering_also_respects_the_document_filter():
    """The document filter must scope the whole Dashboard (product list,
    department chart) consistently with the Division table above it - the
    same inFilterRange() predicate every other section already shares."""
    source = _dashboard_source()
    start = source.index("const inFilterRange = (p) => {")
    end = source.index("\n  };", start)
    body = source[start:end]
    assert "dashboardDocumentFilter" in body
    assert "p.docId !== dashboardDocumentFilter" in body
