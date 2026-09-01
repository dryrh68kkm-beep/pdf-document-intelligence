"""User request: make run.bat open the app in Chrome specifically, rather
than whatever the OS default browser happens to be.

run.bat is a Windows batch file with no interpreter available in this
Linux test environment - source-level regression guards, matching this
project's established pattern for non-Python source this suite can't
execute directly (see e.g. test_documents_view_pdf.py for the equivalent
approach on a frontend view module).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_BAT = ROOT / "run.bat"


def _source() -> str:
    return RUN_BAT.read_text(encoding="utf-8")


def test_checks_all_three_real_chrome_install_locations():
    """A real Chrome install lands in one of exactly three places: the
    64-bit or 32-bit Program Files (machine-wide, needs admin) or
    LocalAppData (per-user, no admin rights needed) - missing the last one
    would silently fail to find Chrome on a locked-down corporate machine."""
    source = _source()
    assert r"%ProgramFiles%\Google\Chrome\Application\chrome.exe" in source
    assert r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" in source
    assert r"%LocalAppData%\Google\Chrome\Application\chrome.exe" in source


def test_launches_chrome_explicitly_when_found():
    source = _source()
    assert 'start "" "%CHROME_EXE%" http://localhost:8000' in source


def test_falls_back_to_default_browser_when_chrome_is_not_installed():
    """A machine without Chrome must still open the app somehow - the
    original plain `start "" http://localhost:8000` behavior must survive
    as the else branch, not be replaced outright."""
    source = _source()
    assert "if defined CHROME_EXE (" in source
    assert ") else (\n  start \"\" http://localhost:8000\n)" in source


def test_stays_plain_ascii():
    """install.bat's own comment explains why: chcp 65001 + non-ASCII text
    corrupted the batch parser on real Windows 10 machines (build 17763
    confirmed) - any new lines added to run.bat must not reintroduce that."""
    source = _source()
    assert all(ord(ch) < 128 for ch in source)


def test_still_starts_the_uvicorn_server():
    """Regression guard: the browser-launch logic must not have replaced or
    displaced the actual server start-up line."""
    source = _source()
    assert "uvicorn pdf_document_intelligence.api.app:app --host 0.0.0.0 --port 8000" in source
