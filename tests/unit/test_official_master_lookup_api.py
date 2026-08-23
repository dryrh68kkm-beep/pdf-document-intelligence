"""GET /api/master/official/lookup - single-barcode existence check against
the Official Master (user-reported: the Product Master page's search box
only searches the small Local Verified list, so a real barcode that IS in
the ~50k-row Official Master shows nothing, and the user can't tell whether
their import actually worked)."""
from __future__ import annotations

import csv

import pytest
from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.catalog import loader as loader_module
from pdf_document_intelligence.catalog import snapshot as snapshot_module


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    source = tmp_path / "external_master.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "BARCODE", "ART_SV_NAME", "SUBCLASS_NAME", "ART_NO",
                "DEPARTMENT_NAME", "DIVISION_NAME",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "BARCODE": "200000793473", "ART_SV_NAME": "Test Product",
            "SUBCLASS_NAME": "SUB", "ART_NO": "ART1",
            "DEPARTMENT_NAME": "HBA", "DIVISION_NAME": "04 DRY FOOD",
        })

    data_dir = tmp_path / "data_dir"
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(data_dir))

    snapshot_module.import_catalog_snapshot(source, overwrite=True)
    loader_module.get_default_catalog.cache_clear()
    yield
    loader_module.get_default_catalog.cache_clear()


def test_lookup_found(catalog):
    client = TestClient(app)
    res = client.get("/api/master/official/lookup", params={"barcode": "200000793473"})
    assert res.status_code == 200
    body = res.json()
    assert body["found"] is True
    assert body["barcode"] == "200000793473"
    assert body["name"] == "Test Product"
    assert body["articleCode"] == "ART1"


def test_lookup_not_found(catalog):
    client = TestClient(app)
    res = client.get("/api/master/official/lookup", params={"barcode": "999999999999"})
    assert res.status_code == 200
    assert res.json() == {"found": False}


def test_lookup_requires_barcode_param(catalog):
    client = TestClient(app)
    res = client.get("/api/master/official/lookup")
    assert res.status_code == 422
