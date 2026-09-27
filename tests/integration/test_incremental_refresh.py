"""Incremental Dashboard refresh (user request: re-fetching every document/
row on every refresh got slow as the document count grew) - GET /api/documents
and GET /api/products with a `since` cursor should return only what changed,
including a just-deleted document/row (deletedAt set) so the caller can
prune it, and a document whose only change was a row correction (which
never touches the document's own updated_at - see
Repository.list_documents_since()'s docstring).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store


@pytest.fixture(autouse=True)
def _isolated_store():
    store.reset_for_tests()
    yield
    store.reset_for_tests()


def _upload(client: TestClient, filename: str = "doc.pdf") -> str:
    from tests.synthetic_documents import make_bigc_pdf
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        pdf_path = make_bigc_pdf(Path(tmp) / filename)
        with pdf_path.open("rb") as f:
            res = client.post("/api/documents", files={"file": (filename, f, "application/pdf")})
    assert res.status_code == 200
    return res.json()["id"]


def _wait_complete(client: TestClient, doc_id: str, timeout: int = 120) -> dict:
    import time

    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] in ("complete", "error"):
            return doc
        time.sleep(0.5)
    raise TimeoutError("document did not finish processing in time")


def test_since_with_no_changes_returns_empty():
    client = TestClient(app)
    doc_id = _upload(client)
    _wait_complete(client, doc_id)
    baseline = client.get("/api/documents").json()
    cursor = max(d["updatedAt"] for d in baseline)

    res = client.get("/api/documents", params={"since": cursor})
    assert res.status_code == 200
    assert res.json() == []

    res = client.get("/api/products", params={"since": cursor})
    assert res.status_code == 200
    assert res.json() == []


def test_since_picks_up_a_newly_uploaded_document():
    client = TestClient(app)
    first_id = _upload(client, "first.pdf")
    _wait_complete(client, first_id)
    cursor = max(d["updatedAt"] for d in client.get("/api/documents").json())

    second_id = _upload(client, "second.pdf")
    _wait_complete(client, second_id)

    res = client.get("/api/documents", params={"since": cursor})
    assert res.status_code == 200
    ids = [d["id"] for d in res.json()]
    assert second_id in ids
    assert first_id not in ids


def test_since_picks_up_a_deleted_document():
    client = TestClient(app)
    doc_id = _upload(client)
    _wait_complete(client, doc_id)
    cursor = max(d["updatedAt"] for d in client.get("/api/documents").json())

    res = client.delete(f"/api/documents/{doc_id}")
    assert res.status_code == 200

    res = client.get("/api/documents", params={"since": cursor})
    assert res.status_code == 200
    docs = res.json()
    assert len(docs) == 1
    assert docs[0]["id"] == doc_id
    assert docs[0]["deletedAt"] is not None

    # It must no longer appear in the plain (non-incremental) active list.
    res = client.get("/api/documents")
    assert doc_id not in [d["id"] for d in res.json()]


def test_since_picks_up_a_document_whose_only_change_is_a_row_correction():
    """The document row's own updated_at never moves on a correction -
    only the corrected product_row's does. The document must still be
    returned, because its embedded rowCount/totalAmount stats are
    recomputed from that same row at request time."""
    client = TestClient(app)
    doc_id = _upload(client)
    _wait_complete(client, doc_id)
    cursor = max(d["updatedAt"] for d in client.get("/api/documents").json())

    products = client.get("/api/products").json()
    row = next(p for p in products if p["docId"] == doc_id)
    res = client.patch(
        f"/api/products/{row['rowId']}",
        json={"field": "name", "value": "Corrected Name", "reason": "test"},
    )
    assert res.status_code == 200

    res = client.get("/api/documents", params={"since": cursor})
    assert res.status_code == 200
    ids = [d["id"] for d in res.json()]
    assert doc_id in ids

    res = client.get("/api/products", params={"since": cursor})
    assert res.status_code == 200
    rows = res.json()
    assert any(r["rowId"] == row["rowId"] and r["fields"]["name"]["value"] == "Corrected Name" for r in rows)


def test_since_picks_up_a_deleted_product_row():
    """A reprocess replaces a row by soft-deleting the old one and
    inserting a new one *when the new extraction no longer matches it*
    (repository.py's own match-by-barcode/article/row_index rule) - the
    incremental caller must see the deleted row (deletedAt set) to prune
    it locally, not just the new replacement. Exercised directly against
    the repository (like test_division_summary_resilience.py) with a
    genuinely different barcode on reprocess, rather than through the real
    HTTP endpoint/OCR pipeline, which would re-extract the same synthetic
    PDF's unchanged content and match (reuse) the same row - never
    exercising the soft-delete path this test is actually about."""
    from pdf_document_intelligence.api.rows import persist_document_result
    from tests.unit.db_helpers import make_result, make_row

    client = TestClient(app)
    doc_id = _upload(client)
    _wait_complete(client, doc_id)
    cursor = max(d["updatedAt"] for d in client.get("/api/documents").json())

    new_row = make_row(0, "BAKERY", "8850000000099", "ARTNEW", "สินค้าใหม่", 1.0, 1, 1)
    persist_document_result(doc_id, make_result(doc_id, "doc.pdf", [("BAKERY", [new_row])]), store.repo)

    res = client.get("/api/products", params={"since": cursor})
    assert res.status_code == 200
    rows = res.json()
    assert any(r["deletedAt"] is not None for r in rows)
    assert any(r["deletedAt"] is None for r in rows)
