from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "frontend" / "app" / "views" / "dashboard.js"
STATE = ROOT / "frontend" / "app" / "state.js"
INDEX = ROOT / "frontend" / "app" / "index.html"

# The redesign (redesign/enterprise-ui) replaced the standalone
# phase4-dashboard.css hardcoded-hex Executive Overview with a token-driven
# rebuild inside dashboard.js + styles.css.
#
# A later pass (user request: consolidate the Dashboard to one page) removed
# the standalone "Department Overview" and "Recent Documents" sections.
#
# A later pass (user request) made the Dashboard answer "today's products ->
# which department -> how many -> how much" for one document date at a
# time, navigable day by day.
#
# Most recent pass (user request, with a reference mockup): the day-by-day
# navigator was replaced by a document-date RANGE filter plus an optional
# Division filter, a Division-level donut + summary table (value-based,
# falling back to a quantity-based breakdown when no document in range has
# amount data) with a total row footing to 100%, and a header showing when
# data was last refreshed. Quality Score / Data Quality / Reconciliation /
# Document Type / Division Overview all remain off the page - moved into
# one slim status strip that links into Documents/Review, where that detail
# is actually actionable.


def test_dashboard_surfaces_the_three_kpis():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "มูลค่ารวม" in source
    assert "จำนวนรายการ" in source
    assert "จำนวนเอกสาร" in source


def test_dashboard_surfaces_product_table_and_department_breakdown():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "รายการสินค้า" in source
    # A horizontal color-coded bar chart of which department has the most
    # product by quantity (user request: changed from a donut to bars),
    # alongside the Division donut card and full summary table (user
    # request, with a reference mockup - split into two sections: a
    # compact donut+legend card, and a fuller table with an Action column).
    assert "renderDepartmentBarChart" in source
    assert "renderDivisionDonutCard" in source
    assert "renderDivisionSummaryTable" in source
    # The table's columns (user request, with a reference mockup: bring
    # back ราคาต่อหน่วย alongside the summarized total value - both sourced
    # from the same backend fields, never recomputed on the frontend):
    # name, article, barcode, division/department, quantity, unit price,
    # amount, status.
    assert "sku_qty" in source
    assert "unit_price" in source
    assert ".amount" in source
    # Clicking a row still opens the existing product detail/evidence panel
    # - not a second, duplicate detail implementation.
    assert 'openPanel({ type: "product"' in source


def test_dashboard_product_list_has_search_filter_sort():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "dashProductSearch" in source
    assert "dashProductDeptSelect" in source
    assert "dashProductSortSelect" in source
    assert "localSearchText" in source


def test_dashboard_division_colors_are_stable_not_render_order():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "DIVISION_COLOR_BY_NAME" in source
    assert "colorForDivision" in source


def test_dashboard_has_date_range_shortcuts():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "วันนี้" in source
    assert "เมื่อวาน" in source
    assert "เดือนนี้" in source


def test_decorative_system_status_removed_from_sidebar():
    sidebar = (ROOT / "frontend" / "app" / "components" / "sidebar.js").read_text(encoding="utf-8")
    assert "System Status" not in sidebar
    assert "Operational" not in sidebar


def test_dashboard_has_a_date_range_and_division_filter():
    dashboard_source = DASHBOARD.read_text(encoding="utf-8")
    state_source = STATE.read_text(encoding="utf-8")
    # Replaces the earlier day-by-day navigator (user request, with a
    # reference mockup: a date-range picker plus a Division dropdown).
    assert "dashboardDateFrom" in state_source
    assert "dashboardDateTo" in state_source
    assert "dashboardDivisionFilter" in state_source
    assert "setDashboardOverviewFilters" in state_source
    assert "dashDateFrom" in dashboard_source
    assert "dashDateTo" in dashboard_source
    assert "dashDivisionSelect" in dashboard_source
    # No leftover day-navigator plumbing.
    assert "dashboardSelectedDate" not in state_source
    assert "dashboardSelectedDate" not in dashboard_source


def test_dashboard_shows_last_refreshed_and_a_refresh_control():
    dashboard_source = DASHBOARD.read_text(encoding="utf-8")
    state_source = STATE.read_text(encoding="utf-8")
    assert "dashboardLastRefreshedAt" in state_source
    assert "dashboardRefreshing" in state_source
    assert "dashboardLastRefreshedAt" in dashboard_source
    assert "dashRefreshBtn" in dashboard_source


def test_dashboard_uses_document_date_not_upload_date():
    dashboard_source = DASHBOARD.read_text(encoding="utf-8")
    state_source = STATE.read_text(encoding="utf-8")
    assert ".documentDate" in state_source
    assert "uploadedAt" not in dashboard_source


def test_dashboard_overview_sourced_from_authoritative_division_summary_api():
    # Never invent a qty*price formula on the frontend - the Division
    # totals/percentages must come from the same Decimal-safe endpoint that
    # already powers Division Detail (see api/divisions.py), aggregated in
    # state.js's _computeDashboardOverview().
    state_source = STATE.read_text(encoding="utf-8")
    assert "_computeDashboardOverview" in state_source
    assert "getDivisions" in state_source


def test_division_table_percentages_foot_to_100():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "allocatePercentages" in source


def test_quality_and_reconciliation_detail_moved_off_dashboard():
    source = DASHBOARD.read_text(encoding="utf-8")
    # The big cards are gone from the Dashboard itself...
    assert "Data Quality" not in source
    assert "Reconciliation Summary" not in source
    assert "Document Type" not in source
    # ...replaced by one slim strip that links out to where they now live.
    assert "dash-status-strip" in source


def test_phase4_dashboard_stylesheet_was_retired():
    html = INDEX.read_text(encoding="utf-8")
    assert "phase4-dashboard.css" not in html
    assert not (ROOT / "frontend" / "app" / "phase4-dashboard.css").exists()


def test_dashboard_has_no_hardcoded_hex_colors():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "DIVISION_COLORS" not in source
    assert "#3478f6" not in source
