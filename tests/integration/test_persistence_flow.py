"""End-to-end persistence flow using runtime-generated synthetic PDFs only.

No real user/company PDF or derived business data is stored in this test.
"""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store
from pdf_document_intelligence.db.connection import get_connection
from pdf_document_intelligence.db.paths import get_db_path
from tests.synthetic_pdf import make_bigc_pdf


def _wait_complete(client: TestClient, doc_id: str, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] in ("complete", "error"):
            return doc
        time.sleep(1)
    raise TimeoutError("document did not finish processing in time")


def test_upload_edit_restart_flow(tmp_path):
    store.reset_for_tests()
    client = TestClient(app)
    sample = make_bigc_pdf(tmp_path / "synthetic_bigc.pdf")

    with sample.open("rb") as f:
        res = client.post("/api/documents", files={"file": ("synthetic_bigc.pdf", f, "application/pdf")})
    assert res.status_code == 200
    doc_id = res.json()["id"]

    doc = _wait_complete(client, doc_id)
    assert doc["status"] == "complete"

    state = client.get("/api/state").json()
    assert state["rowCount"] > 0
    before_row_count = state["rowCount"]

    products = client.get("/api/products").json()
    target = next(
        p for p in products
        if not p["suspectedNonProduct"] and p["fields"]["sku_qty"]["value"] is not None
    )
    row_id = target["rowId"]
    old_sku_qty = target["fields"]["sku_qty"]["value"]

    patch_res = client.patch(
        f"/api/products/{row_id}",
        json={"field": "sku_qty", "value": old_sku_qty + 50, "reason": "synthetic fixture verification"},
    )
    assert patch_res.status_code == 200

    state_after_edit = client.get("/api/state").json()
    assert state_after_edit["grandTotals"]["sku_qty"] == state["grandTotals"]["sku_qty"] + 50

    history = client.get(f"/api/products/{row_id}/history").json()
    assert len(history) == 1
    assert history[0]["field"] == "sku_qty"

    get_connection().close()
    import pdf_document_intelligence.db.connection as connection_module

    connection_module._conn = None
    get_connection(get_db_path())

    documents_after_restart = client.get("/api/documents").json()
    assert len(documents_after_restart) == 1
    assert documents_after_restart[0]["status"] == "complete"

    state_after_restart = client.get("/api/state").json()
    assert state_after_restart["rowCount"] == before_row_count
    assert state_after_restart["grandTotals"]["sku_qty"] == state_after_edit["grandTotals"]["sku_qty"]

    history_after_restart = client.get(f"/api/products/{row_id}/history").json()
    assert len(history_after_restart) == 1

    with sample.open("rb") as f:
        dup_res = client.post("/api/documents", files={"file": ("synthetic_bigc.pdf", f, "application/pdf")})
    assert dup_res.status_code == 409


def test_local_master_learning_flow():
    store.reset_for_tests()
    client = TestClient(app)

    add_res = client.post(
        "/api/master/local",
        json={"barcode": "9990000012345", "productName": "SYNTHETIC CONFIRMED ITEM", "department": "SYNTHETIC"},
    )
    assert add_res.status_code == 200
    assert add_res.json()["created"] is True

    dup_res = client.post(
        "/api/master/local",
        json={"barcode": "9990000012345", "productName": "OTHER SYNTHETIC NAME", "department": "SYNTHETIC"},
    )
    assert dup_res.json()["created"] is False

    listing = client.get("/api/master/local").json()
    assert listing["count"] == 1


def test_health_endpoint_reports_real_state():
    store.reset_for_tests()
    client = TestClient(app)
    health = client.get("/api/health").json()
    assert health["status"] in ("ok", "degraded")
    assert health["productMaster"]["officialCount"] > 0
    assert "schemaVersion" in health["database"]
    assert isinstance(health["ocr"]["available"], bool)


def test_backup_and_restore_roundtrip():
    store.reset_for_tests()
    client = TestClient(app)
    client.post("/api/master/local", json={"barcode": "111", "productName": "x", "department": "A"})

    backup_res = client.post("/api/backup")
    assert backup_res.status_code == 200
    backup_bytes = backup_res.content

    client.post("/api/master/local", json={"barcode": "222", "productName": "y", "department": "B"})
    assert client.get("/api/master/local").json()["count"] == 2

    restore_res = client.post(
        "/api/restore", files={"file": ("backup.zip", backup_bytes, "application/zip")}
    )
    assert restore_res.status_code == 200
    assert client.get("/api/master/local").json()["count"] == 1
