from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "frontend" / "app" / "state.js"
MAIN = ROOT / "frontend" / "app" / "main.js"
API_JS = ROOT / "frontend" / "app" / "api.js"
APP_PY = ROOT / "pdf_document_intelligence" / "api" / "app.py"


def test_phase5_improves_existing_dashboard_path_without_parallel_endpoint():
    state = STATE.read_text(encoding="utf-8")
    api_js = API_JS.read_text(encoding="utf-8")
    app_py = APP_PY.read_text(encoding="utf-8")

    assert "_pruneDivisionCache" in state
    assert "invalidateDivisionSummary" in state
    assert "this._divisionCache.clear()" not in state
    assert "dashboard-overview" not in api_js
    assert "dashboard-overview" not in app_py


def test_phase5_invalidates_only_the_edited_document_before_refresh():
    main = MAIN.read_text(encoding="utf-8")
    handler = main.split('document.addEventListener("product-saved"', 1)[1].split("});", 1)[0]

    assert "changedDocId" in handler
    assert "store.invalidateDivisionSummary(changedDocId)" in handler
    assert handler.index("store.invalidateDivisionSummary(changedDocId)") < handler.index("store.refreshAll()")
