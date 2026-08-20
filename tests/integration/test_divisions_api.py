"""Dashboard Phase 1: GET /api/analytics/documents/{id}/divisions and
.../divisions/{code}/departments. Uses synthetic rows (tests/unit/db_helpers)
against real department names from data/department_hierarchy.csv so the
division mapping under test is the real one, not a stub.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.rows import prepare_flat_rows
from pdf_document_intelligence.api.store import store
from tests.unit.db_helpers import make_result, make_row


def _reset_store():
    store.reset_for_tests()


def _complete(doc_id, filename, tables):
    result = make_result(doc_id, filename, tables)
    flat = prepare_flat_rows(doc_id, result, store.repo)
    return store.repo.complete_document_with_rows(doc_id, 1, {"confidence": 0.9}, flat)


def test_division_totals_reconcile_to_document_totals():
    _reset_store()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    tables = [
        ("HBA", [make_row(0, "HBA", "BC1", "ART1", "Product 1", 10.0, 2, 20)]),
        ("HOUSEWARE", [make_row(0, "HOUSEWARE", "BC2", "ART2", "Product 2", 5.0, 1, 10)]),
        ("BUTCHERY", [make_row(0, "BUTCHERY", "BC3", "ART3", "Product 3", 3.0, 1, 5)]),
    ]
    _complete(doc["id"], "t.pdf", tables)

    client = TestClient(app)
    resp = client.get(f"/api/analytics/documents/{doc['id']}/divisions")
    assert resp.status_code == 200
    body = resp.json()

    assert len(body["divisions"]) == 6

    summed = {"rowCount": 0, "weight": 0.0, "puQty": 0.0, "skuQty": 0.0}
    for d in body["divisions"]:
        summed["rowCount"] += d["rowCount"]
        summed["weight"] += d["weight"]
        summed["puQty"] += d["puQty"]
        summed["skuQty"] += d["skuQty"]

    totals = body["documentTotals"]
    assert summed["rowCount"] == totals["rowCount"] == 3
    assert round(summed["weight"], 3) == totals["weight"]
    assert round(summed["puQty"], 3) == totals["puQty"]
    assert round(summed["skuQty"], 3) == totals["skuQty"]
    assert body["dataQuality"]["unmappedRowCount"] == 0
    assert body["dataQuality"]["unmappedDepartments"] == []


def test_unmapped_department_does_not_create_seventh_division():
    _reset_store()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    tables = [
        ("HBA", [make_row(0, "HBA", "BC1", "ART1", "Product 1", 10.0, 2, 20)]),
        ("NOT_A_REAL_DEPT", [make_row(0, "NOT_A_REAL_DEPT", "BC9", "ART9", "Unknown", 1.0, 1, 1)]),
    ]
    _complete(doc["id"], "t.pdf", tables)

    client = TestClient(app)
    body = client.get(f"/api/analytics/documents/{doc['id']}/divisions").json()

    assert len(body["divisions"]) == 6
    assert body["dataQuality"]["unmappedRowCount"] == 1
    assert body["dataQuality"]["unmappedDepartments"] == ["NOT_A_REAL_DEPT"]
    # the unmapped row must not be silently folded into any real division
    assert sum(d["rowCount"] for d in body["divisions"]) == 1


def test_department_prefix_variant_maps_same_as_bare_name():
    _reset_store()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    tables = [("0460 HBA", [make_row(0, "0460 HBA", "BC1", "ART1", "Product", 10.0, 2, 20)])]
    _complete(doc["id"], "t.pdf", tables)

    client = TestClient(app)
    body = client.get(f"/api/analytics/documents/{doc['id']}/divisions").json()
    assert body["dataQuality"]["unmappedRowCount"] == 0
    dry_food = next(d for d in body["divisions"] if d["divisionCode"] == "04")
    assert dry_food["rowCount"] == 1


def test_corrected_value_is_used_in_division_totals():
    _reset_store()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    tables = [("HBA", [make_row(0, "HBA", "BC1", "ART1", "Product", 10.0, 2, 20)])]
    _complete(doc["id"], "t.pdf", tables)

    client = TestClient(app)
    row_id = store.repo.list_product_rows(document_id=doc["id"])[0]["id"]
    patch = client.patch(f"/api/products/{row_id}", json={"field": "weight_qty", "value": 99.0, "reason": "fix"})
    assert patch.status_code == 200

    body = client.get(f"/api/analytics/documents/{doc['id']}/divisions").json()
    dry_food = next(d for d in body["divisions"] if d["divisionCode"] == "04")
    assert dry_food["weight"] == 99.0
    assert body["dataQuality"]["corrected"] == 1


def test_soft_deleted_document_returns_404_not_counted():
    _reset_store()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    tables = [("HBA", [make_row(0, "HBA", "BC1", "ART1", "Product", 10.0, 2, 20)])]
    _complete(doc["id"], "t.pdf", tables)
    store.remove(doc["id"])

    client = TestClient(app)
    resp = client.get(f"/api/analytics/documents/{doc['id']}/divisions")
    assert resp.status_code == 404


def test_reprocess_does_not_double_count():
    _reset_store()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    tables = [("HBA", [make_row(0, "HBA", "BC1", "ART1", "Product", 10.0, 2, 20)])]
    _complete(doc["id"], "t.pdf", tables)
    # simulate reprocess: same document id, same extraction re-run
    _complete(doc["id"], "t.pdf", tables)

    client = TestClient(app)
    body = client.get(f"/api/analytics/documents/{doc['id']}/divisions").json()
    dry_food = next(d for d in body["divisions"] if d["divisionCode"] == "04")
    assert dry_food["rowCount"] == 1
    assert body["documentTotals"]["rowCount"] == 1


def test_division_departments_endpoint():
    _reset_store()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    tables = [
        ("HBA", [make_row(0, "HBA", "BC1", "ART1", "Product 1", 10.0, 2, 20)]),
        ("FACE & COSMETICS", [make_row(0, "FACE & COSMETICS", "BC2", "ART2", "Product 2", 5.0, 1, 10)]),
    ]
    _complete(doc["id"], "t.pdf", tables)

    client = TestClient(app)
    resp = client.get(f"/api/analytics/documents/{doc['id']}/divisions/04/departments")
    assert resp.status_code == 200
    body = resp.json()
    assert body["divisionCode"] == "04"
    names = {d["name"] for d in body["departments"]}
    assert names == {"HBA", "FACE & COSMETICS"}


def test_unknown_division_code_404():
    _reset_store()
    doc = store.create("t.pdf", b"%PDF-1.4 fake")
    client = TestClient(app)
    resp = client.get(f"/api/analytics/documents/{doc['id']}/divisions/99/departments")
    assert resp.status_code == 404
