"""GET /api/products and GET /api/documents against the real app/store: a
single document/row with corrupted stored JSON must be skipped, not take
the whole endpoint down with a 500 - see tests/unit/test_serialize_resilience.py
for the underlying pure-function fixes this exercises end to end.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store
from pdf_document_intelligence.db.connection import get_write_lock
from pdf_document_intelligence.db.repository import new_id


@pytest.fixture(autouse=True)
def _isolated_store():
    store.reset_for_tests()
    yield
    store.reset_for_tests()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _insert_document(*, status: str = "complete", meta_json: str | None = None) -> str:
    now = _now()
    doc_id = new_id()
    repo = store.repo
    with get_write_lock(), repo._conn:
        repo._conn.execute(
            """INSERT INTO documents (id, filename, sha256, file_size, status, uploaded_at, created_at, updated_at, meta_json)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (doc_id, "synthetic.pdf", new_id(), 1, status, now, now, now, meta_json),
        )
    return doc_id


def _insert_product_row(document_id: str, *, fields_json: str = "{}") -> str:
    now = _now()
    row_id = new_id()
    repo = store.repo
    with get_write_lock(), repo._conn:
        repo._conn.execute(
            """INSERT INTO product_rows (
                   id, document_id, source_page, row_index, barcode, resolved_product_name,
                   fields_json, corrected_fields_json, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (row_id, document_id, 1, 0, "8850000000001", "Synthetic Product", fields_json, "[]", now, now),
        )
    return row_id


def test_products_endpoint_skips_a_row_with_corrupted_fields_json():
    """The known corruption shapes (bad JSON text, wrong types, ...) are
    now tolerated inside serialize.py itself (see
    tests/unit/test_serialize_resilience.py) - this proves the endpoint's
    own last-resort per-row guard still does its job for whatever
    serialize.py doesn't yet know how to degrade gracefully, by forcing
    one specific row to raise regardless of its actual (valid) data."""
    good_doc = _insert_document()
    good_row_id = _insert_product_row(good_doc, fields_json='{"barcode": {"value": "8850000000001"}}')
    bad_row_id = _insert_product_row(good_doc, fields_json='{"barcode": {"value": "8850000000002"}}')

    import pdf_document_intelligence.api.app as app_module

    real_product_row_json = app_module.product_row_json

    def _flaky_product_row_json(row, doc_filename):
        if row["id"] == bad_row_id:
            raise RuntimeError("simulated unforeseen corruption")
        return real_product_row_json(row, doc_filename)

    app_module.product_row_json = _flaky_product_row_json
    try:
        client = TestClient(app)
        res = client.get("/api/products")
    finally:
        app_module.product_row_json = real_product_row_json

    assert res.status_code == 200
    products = res.json()
    assert [p["rowId"] for p in products] == [good_row_id]


def test_documents_endpoint_skips_a_document_that_fails_to_serialize():
    good_doc = _insert_document()
    bad_doc = _insert_document()

    import pdf_document_intelligence.api.app as app_module

    real_document_summary_json = app_module.document_summary_json

    def _flaky_document_summary_json(doc, stats=None):
        if doc["id"] == bad_doc:
            raise RuntimeError("simulated unforeseen corruption")
        return real_document_summary_json(doc, stats)

    app_module.document_summary_json = _flaky_document_summary_json
    try:
        client = TestClient(app)
        res = client.get("/api/documents")
    finally:
        app_module.document_summary_json = real_document_summary_json

    assert res.status_code == 200
    docs = res.json()
    assert [d["id"] for d in docs] == [good_doc]
