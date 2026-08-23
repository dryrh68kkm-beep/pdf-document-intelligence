from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "frontend" / "app" / "views" / "dashboard.js"
STATE = ROOT / "frontend" / "app" / "state.js"
INDEX = ROOT / "frontend" / "app" / "index.html"


def test_phase4_dashboard_keeps_approved_minimal_scope():
    source = DASHBOARD.read_text(encoding="utf-8")
    assert "มูลค่ารวม" in source
    assert "จำนวนรายการ" in source
    assert "จำนวนเอกสาร" in source
    assert "สัดส่วนมูลค่าตาม Division" in source
    assert "phase4DateFrom" in source
    assert "phase4DateTo" in source
    assert "phase4Division" in source
    assert "แนวโน้ม" not in source
    assert "Quality Score" not in source


def test_phase4_dashboard_uses_document_date_not_upload_date():
    dashboard_source = DASHBOARD.read_text(encoding="utf-8")
    state_source = STATE.read_text(encoding="utf-8")
    assert "document.documentDate" in state_source
    assert "uploadedAt" not in dashboard_source
    assert "ไม่ใช่วันที่อัปโหลด" in dashboard_source


def test_phase4_dashboard_stylesheet_is_loaded():
    html = INDEX.read_text(encoding="utf-8")
    assert '<link rel="stylesheet" href="/phase4-dashboard.css" />' in html
