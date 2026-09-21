"""GET /api/expiry-link/summary against the real app/store - no mocked
pipeline needed since this endpoint only reads a CSV off disk and this
app's own already-persisted product_rows prices; see
tests/unit/test_expiry_link.py for the pure CSV-parsing/matching logic.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store
from pdf_document_intelligence.catalog.expiry_link import EXPIRY_LINK_ENV


@pytest.fixture(autouse=True)
def _isolated_store():
    store.reset_for_tests()
    yield
    store.reset_for_tests()


def test_summary_not_configured_when_env_unset(monkeypatch):
    monkeypatch.delenv(EXPIRY_LINK_ENV, raising=False)
    client = TestClient(app)
    res = client.get("/api/expiry-link/summary")
    assert res.status_code == 200
    assert res.json() == {
        "configured": False, "available": False, "fileFound": False,
        "itemCount": 0, "matchedCount": 0, "unmatchedCount": 0, "totalValue": 0.0,
    }


def test_summary_configured_but_source_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv(EXPIRY_LINK_ENV, str(tmp_path / "NEARLY_EXPIRED_1003.csv"))
    client = TestClient(app)
    res = client.get("/api/expiry-link/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["available"] is False
    assert body["fileFound"] is False


def test_summary_matches_products_when_source_file_present(monkeypatch, tmp_path):
    csv_path = tmp_path / "NEARLY_EXPIRED_1003.csv"
    csv_path.write_text(
        "BAR_CODE,DESCRIPTION,STOCK_QTY,DAY_LEFT,SUB_DEPT_NAME,DIV,DEPT\n"
        "8850001,Product A,5,3,SUB,D01,DEPT1\n"
        "8850099,Unmatched Product,2,1,SUB,D01,DEPT1\n",
        encoding="utf-8-sig",
    )
    monkeypatch.setenv(EXPIRY_LINK_ENV, str(csv_path))
    _insert_priced_row(barcode="8850001", unit_price=10.0)

    client = TestClient(app)
    res = client.get("/api/expiry-link/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["configured"] is True
    assert body["available"] is True
    assert body["itemCount"] == 2
    assert body["matchedCount"] == 1
    assert body["unmatchedCount"] == 1
    assert body["totalValue"] == 50.0


def _insert_priced_row(barcode: str, unit_price: float) -> None:
    """Minimal direct insert into product_rows via the real repository -
    only the columns latest_unit_prices_by_barcode() reads matter here."""
    import json
    from datetime import datetime, timezone

    from pdf_document_intelligence.db.connection import get_write_lock
    from pdf_document_intelligence.db.repository import new_id

    now = datetime.now(timezone.utc).isoformat()
    repo = store.repo
    document_id = new_id()
    with get_write_lock(), repo._conn:
        repo._conn.execute(
            """INSERT INTO documents (id, filename, sha256, file_size, status, uploaded_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (document_id, "synthetic.pdf", new_id(), 1, "complete", now, now, now),
        )
        repo._conn.execute(
            """INSERT INTO product_rows (
                   id, document_id, source_page, row_index, barcode, resolved_product_name,
                   sku_qty, unit_price, amount, fields_json, corrected_fields_json,
                   created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                new_id(), document_id, 1, 0, barcode, "Synthetic Product",
                1.0, unit_price, unit_price, "{}", "[]", now, now,
            ),
        )
