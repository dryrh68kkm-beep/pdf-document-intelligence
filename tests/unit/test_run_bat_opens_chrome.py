"""Windows launcher/stopper source-level regression guards.

The Linux fast-test job cannot execute .bat files, so the important Windows
ownership/readiness invariants are pinned by source inspection while the
real Windows E2E job covers the application itself.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_BAT = ROOT / "run.bat"
STOP_BAT = ROOT / "stop.bat"
RUN_SERVER = ROOT / "scripts" / "run_server.py"


def test_run_bat_uses_owned_python_launcher():
    source = RUN_BAT.read_text(encoding="utf-8")
    assert r"python scripts\run_server.py" in source
    assert "uvicorn pdf_document_intelligence.api.app:app" not in source


def test_launcher_waits_for_health_before_opening_browser():
    source = RUN_SERVER.read_text(encoding="utf-8")
    assert 'HEALTH_URL = f"{URL}/api/health"' in source
    assert "if _app_is_ready():" in source
    assert "_open_browser()" in source
    assert "time.sleep(0.25)" in source


def test_launcher_checks_all_three_chrome_install_locations():
    source = RUN_SERVER.read_text(encoding="utf-8")
    assert '"ProgramFiles"' in source
    assert '"ProgramFiles(x86)"' in source
    assert '"LocalAppData"' in source
    assert '"Google" / "Chrome" / "Application" / "chrome.exe"' in source


def test_launcher_preserves_lan_binding():
    source = RUN_SERVER.read_text(encoding="utf-8")
    assert 'host="0.0.0.0"' in source
    assert "port=8000" in source


def test_stop_bat_requires_pid_ownership_and_port_ownership_before_taskkill():
    source = STOP_BAT.read_text(encoding="utf-8")
    assert r"python scripts\server_pid_path.py" in source
    assert "Get-CimInstance Win32_Process" in source
    assert r"*scripts\run_server.py*" in source
    assert 'if "%%a"=="%APPPID%"' in source
    assert "taskkill /F /T /PID %APPPID%" in source
    # Regression: the old implementation killed every PID returned by
    # netstat on :8000, even if another application owned that port.
    assert "taskkill /F /PID %%a" not in source


def test_windows_batch_files_stay_plain_ascii():
    for path in (RUN_BAT, STOP_BAT):
        source = path.read_text(encoding="utf-8")
        assert all(ord(ch) < 128 for ch in source)
