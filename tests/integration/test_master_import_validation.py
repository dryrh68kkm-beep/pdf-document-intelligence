"""PR6: a bad master catalog file must never overwrite a good one.

import_catalog_snapshot() itself (catalog/snapshot.py) stays a permissive
primitive - it's also how the app imports hierarchy-only reference data
with no product rows at all (the whole test suite's own synthetic
fixtures rely on this via ensure_catalog_snapshot()). The validation
tested here lives one layer up, specific to the user-facing
POST /api/master/import endpoint, which is unambiguously about
barcode/product data.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.catalog import import_validation as import_validation_module
from pdf_document_intelligence.catalog import loader as loader_module
from pdf_document_intelligence.catalog import snapshot as snapshot_module


@pytest.fixture()
def isolated_snapshot_dir(tmp_path, monkeypatch):
    """Redirects PDF_INTELLIGENCE_DATA_DIR (and therefore
    snapshot_module.get_snapshot_path()) at a throwaway directory, so a
    test can control the exact before/after snapshot state without
    touching the shared session catalog every other test relies on."""
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(tmp_path))
    return tmp_path


def _csv(header: str, *rows: str) -> bytes:
    return (header + "\n" + "\n".join(rows) + ("\n" if rows else "")).encode()


GOOD_HEADER = "BARCODE,ART_SV_NAME,SUBCLASS_NAME,ART_NO,DEPARTMENT_NAME,DIVISION_NAME,CURRENT_COST"


def _good_csv(n: int, with_cost: bool = True) -> bytes:
    rows = [
        f"990000000{i:03d},Product {i},SUB,ART{i},BAKERY,04 DRY FOOD,{'12.50' if with_cost else ''}"
        for i in range(n)
    ]
    return _csv(GOOD_HEADER, *rows)


def test_import_with_no_barcode_column_is_rejected(isolated_snapshot_dir):
    client = TestClient(app)
    csv_bytes = _csv("ART_SV_NAME,DEPARTMENT_NAME,DIVISION_NAME", "Product 1,BAKERY,04 DRY FOOD")
    res = client.post("/api/master/import", files={"file": ("m.csv", csv_bytes, "text/csv")})
    assert res.status_code == 400
    assert "no usable product rows" in res.json()["detail"].lower()


def test_import_with_no_name_column_is_rejected(isolated_snapshot_dir):
    client = TestClient(app)
    csv_bytes = _csv("BARCODE,DEPARTMENT_NAME,DIVISION_NAME", "9900000001,BAKERY,04 DRY FOOD")
    res = client.post("/api/master/import", files={"file": ("m.csv", csv_bytes, "text/csv")})
    assert res.status_code == 400
    assert "no usable product rows" in res.json()["detail"].lower()


def test_import_with_zero_data_rows_is_rejected(isolated_snapshot_dir):
    client = TestClient(app)
    csv_bytes = _csv(GOOD_HEADER)  # header only, no rows
    res = client.post("/api/master/import", files={"file": ("m.csv", csv_bytes, "text/csv")})
    assert res.status_code == 400


def test_bad_new_master_leaves_old_master_usable(isolated_snapshot_dir):
    """The core guarantee: importing a good catalog, then a bad file,
    must leave the GOOD catalog intact and fully queryable - not empty,
    not partially overwritten."""
    client = TestClient(app)

    good = client.post("/api/master/import", files={"file": ("good.csv", _good_csv(20), "text/csv")})
    assert good.status_code == 200
    assert good.json()["productCount"] == 20

    bad = client.post("/api/master/import", files={"file": ("bad.csv", _csv(GOOD_HEADER), "text/csv")})
    assert bad.status_code == 400

    status = client.get("/api/master/snapshot/status")
    assert status.json()["productCount"] == 20

    catalog = snapshot_module.load_catalog_snapshot()
    assert len(catalog["products"]) == 20


def test_rejected_candidate_is_never_visible_to_live_catalog_readers(isolated_snapshot_dir, monkeypatch):
    """A bad upload must never become the active snapshot, even briefly.

    Regression for the old write-then-validate implementation: the endpoint
    replaced the live snapshot first, then validate_payload() rejected it and
    restored the old bytes.  A processing worker (or any catalog lookup)
    running inside that window could read and lru-cache the bad catalog; the
    later byte rollback did not clear that cache.  Observe the live catalog
    *during validation* to prove the old, good snapshot stays active until a
    candidate has actually passed validation.
    """
    client = TestClient(app)
    good = client.post("/api/master/import", files={"file": ("good.csv", _good_csv(20), "text/csv")})
    assert good.status_code == 200

    loader_module.get_default_catalog.cache_clear()
    observed_live_counts: list[int] = []
    real_validate = import_validation_module.validate_payload

    def observing_validate(payload, previous_payload):
        observed_live_counts.append(len(loader_module.get_default_catalog()))
        return real_validate(payload, previous_payload)

    monkeypatch.setattr(import_validation_module, "validate_payload", observing_validate)
    try:
        bad = client.post("/api/master/import", files={"file": ("bad.csv", _csv(GOOD_HEADER), "text/csv")})
        assert bad.status_code == 400

        # Validation saw the previous 20-row catalog, never the rejected
        # zero-row candidate.  The cache also remains good afterward.
        assert observed_live_counts == [20]
        assert len(loader_module.get_default_catalog()) == 20
        assert len(snapshot_module.load_catalog_snapshot()["products"]) == 20
    finally:
        loader_module.get_default_catalog.cache_clear()


def test_credible_ratio_guard_rejects_a_drastically_smaller_replacement(isolated_snapshot_dir):
    client = TestClient(app)

    big = client.post("/api/master/import", files={"file": ("big.csv", _good_csv(100), "text/csv")})
    assert big.status_code == 200

    tiny = client.post("/api/master/import", files={"file": ("tiny.csv", _good_csv(2), "text/csv")})
    assert tiny.status_code == 400
    assert "far fewer" in tiny.json()["detail"].lower()

    status = client.get("/api/master/snapshot/status")
    assert status.json()["productCount"] == 100


def test_a_smaller_but_not_drastic_replacement_is_allowed(isolated_snapshot_dir):
    """Only the extreme case is fatal - a store legitimately trimming its
    own catalog must not be blocked."""
    client = TestClient(app)

    first = client.post("/api/master/import", files={"file": ("a.csv", _good_csv(100), "text/csv")})
    assert first.status_code == 200

    second = client.post("/api/master/import", files={"file": ("b.csv", _good_csv(50), "text/csv")})
    assert second.status_code == 200
    assert second.json()["productCount"] == 50


def test_good_import_reports_no_warnings(isolated_snapshot_dir):
    client = TestClient(app)
    res = client.post("/api/master/import", files={"file": ("good.csv", _good_csv(10), "text/csv")})
    assert res.status_code == 200
    assert res.json()["warnings"] == []


def test_import_with_no_cost_data_succeeds_with_a_warning(isolated_snapshot_dir):
    """A costless catalog is a real, previously-confirmed use case (seen
    live) - must still import successfully, just with a warning rather
    than silently or fatally."""
    client = TestClient(app)
    res = client.post("/api/master/import", files={"file": ("no-cost.csv", _good_csv(10, with_cost=False), "text/csv")})
    assert res.status_code == 200
    assert any("current_cost" in w.lower() for w in res.json()["warnings"])


def test_hierarchy_only_import_via_ensure_catalog_snapshot_is_unaffected(isolated_snapshot_dir, monkeypatch):
    """The validation added for the HTTP endpoint must not reach the
    lower-level import_catalog_snapshot() primitive at all - confirms a
    hierarchy-only file (no BARCODE/ART_SV_NAME, only department/division
    columns - what ensure_catalog_snapshot()'s env-var-triggered auto
    import uses in this test suite's own fixtures) still imports fine."""
    source = isolated_snapshot_dir / "hierarchy_only.csv"
    source.write_text("DEPARTMENT_NAME,DIVISION_NAME\nBAKERY,04 DRY FOOD\n", encoding="utf-8")
    monkeypatch.setenv("PDF_INTELLIGENCE_MASTER_CATALOG", str(source))

    payload = snapshot_module.load_catalog_snapshot()
    assert payload["products"] == []
    assert payload["department_divisions"] == {"BAKERY": "04 DRY FOOD"}
