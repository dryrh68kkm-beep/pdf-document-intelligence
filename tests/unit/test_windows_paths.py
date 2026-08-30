"""Windows-path resolution regression coverage for db/paths.py, runnable
on any OS (monkeypatches sys.platform + the LOCALAPPDATA env var rather
than requiring an actual Windows filesystem) - the Windows CI job's own
tests/windows/test_windows_e2e.py additionally exercises this for real on
windows-latest, creating and writing to the resulting directories on an
actual Windows filesystem; this file is the fast, OS-independent
regression signal for the branch logic itself.
"""
from __future__ import annotations

import importlib
from pathlib import Path


def _reload_paths_module():
    from pdf_document_intelligence.db import paths as paths_module

    return importlib.reload(paths_module)


def test_windows_platform_uses_localappdata(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "LocalAppData"))
    monkeypatch.delenv("PDF_INTELLIGENCE_DATA_DIR", raising=False)
    paths_module = _reload_paths_module()

    data_dir = paths_module.get_data_dir()
    assert str(data_dir).startswith(str(tmp_path / "LocalAppData"))
    assert data_dir.name == paths_module.APP_DIR_NAME
    assert (data_dir / "pdfs").is_dir()
    assert (data_dir / "backups").is_dir()

    # Restore for any test that runs after this one in the same process.
    monkeypatch.undo()
    _reload_paths_module()


def test_windows_platform_falls_back_when_localappdata_unset(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("PDF_INTELLIGENCE_DATA_DIR", raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
    paths_module = _reload_paths_module()

    data_dir = paths_module.get_data_dir()
    assert str(data_dir).startswith(str(fake_home))
    assert "AppData" in str(data_dir) and "Local" in str(data_dir)

    monkeypatch.undo()
    _reload_paths_module()


def test_explicit_data_dir_env_override_takes_priority_on_windows(monkeypatch, tmp_path):
    """PDF_INTELLIGENCE_DATA_DIR (what tests/conftest.py and the Windows
    CI job's own live_server fixture both use for isolation) must win over
    the platform default even when sys.platform reports Windows."""
    monkeypatch.setattr("sys.platform", "win32")
    override = tmp_path / "explicit-override"
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(override))
    paths_module = _reload_paths_module()

    data_dir = paths_module.get_data_dir()
    assert data_dir == override
    assert data_dir.is_dir()

    monkeypatch.undo()
    _reload_paths_module()


def test_db_and_pdf_paths_stay_under_the_resolved_data_dir_on_windows(monkeypatch, tmp_path):
    monkeypatch.setattr("sys.platform", "win32")
    override = tmp_path / "win-data"
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(override))
    paths_module = _reload_paths_module()

    db_path = paths_module.get_db_path()
    pdf_path = paths_module.get_pdf_path("synthetic-doc-id")
    assert db_path.parent == override
    assert pdf_path.parent == override / "pdfs"

    monkeypatch.undo()
    _reload_paths_module()
