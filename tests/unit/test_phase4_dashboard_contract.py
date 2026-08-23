from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "frontend" / "app" / "views" / "dashboard.js"
STATE = ROOT / "frontend" / "app" / "state.js"
INDEX = ROOT / "frontend" / "app" / "index.html"
STYLES = ROOT / "frontend" / "app" / "styles.css"

# The redesign (redesign/enterprise-ui) replaced the standalone
# phase4-dashboard.css hardcoded-hex Executive Overview with a token-driven
# rebuild inside dashboard.js + styles.css. These assertions check the new
# structural/data contract - the same KPI numbers must still be surfaced,
# sourced the same way (document date, not upload date) - rather than the
# retired phase4-* markup.


def test_dashboard_surfaces_core_kpis():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "มูลค่ารวม" in source
    assert "จำนวนรายการ" in source
    assert "จำนวนเอกสาร" in source
    assert "Division Overview" in source
    assert "Department Overview" in source
    assert "Data Quality" in source
    assert "Reconciliation Summary" in source
    assert "Recent Documents" in source


def test_dashboard_surfaces_prominent_quality_score():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "qualityScore" in source
    assert "qualityBand" in source
    assert "quality-banner" in source


def test_dashboard_uses_document_date_not_upload_date():
    dashboard_source = DASHBOARD.read_text(encoding="utf-8")
    state_source = STATE.read_text(encoding="utf-8")
    assert ".documentDate" in state_source
    assert "uploadedAt" not in dashboard_source


def test_phase4_dashboard_stylesheet_was_retired():
    html = INDEX.read_text(encoding="utf-8")
    assert "phase4-dashboard.css" not in html
    assert not (ROOT / "frontend" / "app" / "phase4-dashboard.css").exists()


def test_dashboard_colors_come_from_shared_tokens_not_hardcoded_hex():
    source = DASHBOARD.read_text(encoding="utf-8")
    styles = STYLES.read_text(encoding="utf-8")
    # The old DIVISION_COLORS hardcoded hex array must be gone from JS...
    assert "DIVISION_COLORS" not in source
    assert "#3478f6" not in source
    # ...replaced by CSS custom properties defined once in styles.css.
    assert "--division-1" in styles
    assert "--division-6" in styles
    assert "--division-1" in source
