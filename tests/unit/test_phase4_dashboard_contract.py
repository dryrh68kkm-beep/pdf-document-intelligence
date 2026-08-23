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
# Most recent pass (user request): the Dashboard's job is to answer, the
# instant it opens, "today's products -> which department -> how many -> how
# much" for one document date at a time, not to be a general status board.
# Quality Score / Data Quality / Reconciliation / Document Type / Division
# Overview all moved off the page (collapsed into one slim status strip that
# links into Documents/Review, where that detail is actually actionable) -
# these assertions check the new "daily report" contract replaces them.


def test_dashboard_surfaces_the_three_daily_kpis():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "สินค้าวันนี้" in source
    assert "มูลค่ารวมวันนี้" in source
    assert "แผนกที่มีสินค้าเข้า" in source


def test_dashboard_surfaces_todays_product_table_and_department_breakdown():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "รายการสินค้าวันนี้" in source
    assert "มูลค่าตามแผนกวันนี้" in source
    # The table's columns (user request: drop unit price, keep only the
    # summarized total value): name, article/barcode, department,
    # quantity, amount.
    assert "sku_qty" in source
    assert "unit_price" not in source
    assert ".amount" in source
    # Clicking a row still opens the existing product detail/evidence panel
    # - not a second, duplicate detail implementation.
    assert 'openPanel({ type: "product"' in source


def test_dashboard_has_a_day_by_day_date_navigator():
    dashboard_source = DASHBOARD.read_text(encoding="utf-8")
    state_source = STATE.read_text(encoding="utf-8")
    assert "dashboardSelectedDate" in state_source
    assert "setDashboardSelectedDate" in state_source
    assert "dashboardSelectedDate" in dashboard_source
    assert "shiftIsoDate" in dashboard_source


def test_dashboard_uses_document_date_not_upload_date():
    dashboard_source = DASHBOARD.read_text(encoding="utf-8")
    state_source = STATE.read_text(encoding="utf-8")
    assert ".documentDate" in state_source
    assert "uploadedAt" not in dashboard_source


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
