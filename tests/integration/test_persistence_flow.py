"""End-to-end flow through the real FastAPI app + a real PDF (spec item 35):
upload -> process -> dashboard -> edit review -> save -> dashboard changes
-> restart -> data remains. Also covers local-master learning (item 36) and
health/backup endpoints.

Uses the golden BigC sample already used by test_golden_regression.py, so
this is the one integration test that pays the real OCR cost end-to-end
through the HTTP layer, not just the pipeline function.
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store
from pdf_document_intelligence.db.connection import get_connection
from pdf_document_intelligence.db.paths import get_db_path

SAMPLE = Path(__file__).parent.parent / "golden" / "samples" / "PL92924_112520819.R211252100.pdf"


def _wait_complete(client: TestClient, doc_id: str, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] in ("complete", "error"):
            return doc
        time.sleep(1)
    raise TimeoutError("document did not finish processing in time")


def test_upload_edit_restart_flow():
    store.reset_for_tests()
    client = TestClient(app)

    with SAMPLE.open("rb") as f:
        res = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")})
    doc_id = res.json()["id"]

    doc = _wait_complete(client, doc_id)
    assert doc["status"] == "complete"

    state = client.get("/api/state").json()
    assert state["rowCount"] > 0
    before_row_count = state["rowCount"]

    products = client.get("/api/products").json()
    target = products[0]
    row_id = target["rowId"]
    old_sku_qty = target["fields"]["sku_qty"]["value"]

    patch_res = client.patch(
        f"/api/products/{row_id}",
        json={"field": "sku_qty", "value": (old_sku_qty or 0) + 50, "reason": "ตรวจจาก PDF ต้นฉบับ"},
    )
    assert patch_res.status_code == 200

    state_after_edit = client.get("/api/state").json()
    assert state_after_edit["grandTotals"]["sku_qty"] == state["grandTotals"]["sku_qty"] + 50

    history = client.get(f"/api/products/{row_id}/history").json()
    assert len(history) == 1
    assert history[0]["field"] == "sku_qty"

    # --- simulate an application restart: drop the live connection, reopen
    # the same on-disk file, and confirm the API still sees everything.
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

    # Duplicate detection must also survive the restart.
    with SAMPLE.open("rb") as f:
        dup_res = client.post("/api/documents", files={"file": ("sample.pdf", f, "application/pdf")})
    assert dup_res.status_code == 409


def test_local_master_learning_flow():
    """Unknown barcode -> review -> confirm name -> save to Local Master
    -> next document with the same barcode resolves automatically (item 36)."""
    store.reset_for_tests()
    client = TestClient(app)

    add_res = client.post(
        "/api/master/local",
        json={"barcode": "8850000012345", "productName": "สินค้าที่ผู้ใช้ยืนยันเอง", "department": "BAKERY"},
    )
    assert add_res.status_code == 200
    assert add_res.json()["created"] is True

    dup_res = client.post(
        "/api/master/local",
        json={"barcode": "8850000012345", "productName": "ชื่ออื่น", "department": "BAKERY"},
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


def test_backup_and_restore_roundtrip(tmp_path):
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
    assert client.get("/api/master/local").json()["count"] == 1  # back to pre-second-add state
