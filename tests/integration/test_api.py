"""Fast API wiring tests - deliberately avoid uploading a real PDF here
(that's a ~65s round trip through the full OCR pipeline, already covered
by test_golden_regression.py via the orchestrator directly). These just
confirm the FastAPI app boots, routes correctly, and the store starts
empty - endpoint plumbing, not extraction correctness.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store


def _reset_store():
    store.reset_for_tests()


def test_empty_state():
    _reset_store()
    client = TestClient(app)
    assert client.get("/api/documents").json() == []
    state = client.get("/api/state").json()
    assert state["documentCount"] == 0
    assert state["departments"] == []
    assert client.get("/api/products").json() == []


def test_upload_rejects_non_pdf():
    _reset_store()
    client = TestClient(app)
    res = client.post("/api/documents", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert res.status_code == 400


def test_upload_rejects_empty_file():
    _reset_store()
    client = TestClient(app)
    res = client.post("/api/documents", files={"file": ("empty.pdf", b"", "application/pdf")})
    assert res.status_code == 400


def test_get_missing_document_404():
    _reset_store()
    client = TestClient(app)
    assert client.get("/api/documents/does-not-exist").status_code == 404
    assert client.delete("/api/documents/does-not-exist").status_code == 404


def test_export_with_no_documents_returns_400():
    _reset_store()
    client = TestClient(app)
    assert client.get("/api/export.xlsx").status_code == 400


def test_concurrent_duplicate_upload_returns_409_not_500():
    """Regression guard (L3-003): two concurrent uploads of the same file
    both pass the find_by_hash duplicate check before either commits
    (check-then-act race), so the second one used to hit the sha256
    unique index as an unhandled sqlite3.IntegrityError (500) instead of
    the normal 409 duplicate response."""
    _reset_store()
    client = TestClient(app)
    content = b"%PDF-1.4\n%fake-but-nonempty\n"

    def upload():
        return client.post("/api/documents", files={"file": ("same.pdf", content, "application/pdf")})

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(upload) for _ in range(2)]
        responses = [f.result() for f in futures]

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200, 409], f"expected one accepted + one duplicate, got {statuses}"
