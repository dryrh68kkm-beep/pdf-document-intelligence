"""Regression coverage for the /api/health hardening pass
(api/health.py): additive new checks (Thai OCR pack, writable data/temp
directories, disk space) categorized ok/warning/error, alongside the
pre-existing fields (database.status, productMaster.*, ocr.available)
whose shape and meaning must not change - and confirms the endpoint never
leaks an absolute path, raw exception text, or the admin passphrase.
"""
from __future__ import annotations

import pdf_document_intelligence.api.health as health_module
from pdf_document_intelligence.api.health import check_health
from pdf_document_intelligence.db.repository import get_repository


def test_health_response_keeps_preexisting_fields():
    result = check_health(get_repository())
    assert result["status"] in ("ok", "degraded")
    assert set(result["database"]) == {"status", "schemaVersion", "expectedSchemaVersion"}
    assert set(result["productMaster"]) == {"status", "officialCount", "localCount"}
    assert "available" in result["ocr"]


def test_health_response_adds_new_sections_additively():
    result = check_health(get_repository())
    assert "thaiLanguagePack" in result["ocr"]
    assert result["ocr"]["thaiLanguagePack"]["status"] in ("ok", "warning", "error")
    assert result["dataDirectory"]["writable"] in (True, False)
    assert result["tempDirectory"]["writable"] in (True, False)
    assert result["diskSpace"]["status"] in ("ok", "warning", "error")
    assert isinstance(result["checks"], list) and len(result["checks"]) >= 7
    for check in result["checks"]:
        assert check["status"] in ("ok", "warning", "error")


def test_health_never_leaks_absolute_paths_or_exception_text(monkeypatch):
    """The most likely leak vector: a check's exception branch handing
    str(exc) straight back to the client, which can carry a filesystem
    path (Windows drive letters, home directories) or other internals."""
    import json

    def _boom(*args, **kwargs):
        raise RuntimeError("/home/someuser/.secret/app-data/leaked-path-should-never-appear")

    monkeypatch.setattr(health_module.shutil, "disk_usage", _boom)

    result = check_health(get_repository())
    serialized = json.dumps(result)
    assert "leaked-path-should-never-appear" not in serialized
    assert "/home/" not in serialized
    assert "C:\\" not in serialized


def test_health_never_leaks_admin_passphrase(monkeypatch):
    import json

    from pdf_document_intelligence.api import app as app_module

    monkeypatch.setattr(app_module._settings, "admin_passphrase", "super-secret-passphrase")
    result = check_health(get_repository())
    assert "super-secret-passphrase" not in json.dumps(result)


def test_health_thai_pack_check_never_crashes_without_tesseract(monkeypatch):
    monkeypatch.setattr(health_module.shutil, "which", lambda _: None)
    result = check_health(get_repository())
    assert result["ocr"]["available"] is False
    assert result["ocr"]["thaiLanguagePack"]["available"] is False
    assert result["ocr"]["thaiLanguagePack"]["status"] == "error"


def test_health_endpoint_reachable_via_http():
    from fastapi.testclient import TestClient

    from pdf_document_intelligence.api.app import app

    res = TestClient(app).get("/api/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] in ("ok", "degraded")
    assert "checks" in body
