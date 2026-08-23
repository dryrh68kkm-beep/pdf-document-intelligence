"""GET /api/departments/divisions - flat department->division lookup for the
Dashboard's daily product table (user request: show Division above
Department per row, pulled from the master catalog)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app


def test_department_divisions_endpoint_returns_known_mapping():
    client = TestClient(app)
    res = client.get("/api/departments/divisions")
    assert res.status_code == 200
    body = res.json()
    assert body["HBA"] == {"code": "04", "name": "DRY FOOD"}
    assert body["HOUSEWARE"] == {"code": "02", "name": "HOME LINE"}
    assert body["BUTCHERY"] == {"code": "05", "name": "FRESH FOOD"}


def test_department_divisions_endpoint_excludes_unmapped_departments():
    client = TestClient(app)
    res = client.get("/api/departments/divisions")
    assert "NOT_A_REAL_DEPARTMENT_XYZ" not in res.json()
