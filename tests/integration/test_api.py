"""Fast API wiring tests - deliberately avoid uploading a real PDF here
(that's a ~65s round trip through the full OCR pipeline, already covered
by test_golden_regression.py via the orchestrator directly). These just
confirm the FastAPI app boots, routes correctly, and the store starts
empty - endpoint plumbing, not extraction correctness.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import pdf_document_intelligence.api.app as app_module
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


def test_force_duplicate_reprocesses_existing_document(monkeypatch):
    """FAT-001: force=true must reprocess the existing active document,
    never attempt to create a second active row with the same SHA-256."""
    _reset_store()
    client = TestClient(app)
    content = b"%PDF-1.4\n%fat-001-fixture\n"
    original = store.create("same.pdf", content)
    submitted = []

    class ImmediateCaptureExecutor:
        def submit(self, fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            return None

    monkeypatch.setattr(app_module, "_executor", ImmediateCaptureExecutor())

    duplicate = client.post("/api/documents", files={"file": ("same.pdf", content, "application/pdf")})
    assert duplicate.status_code == 409

    forced = client.post("/api/documents?force=true", files={"file": ("same.pdf", content, "application/pdf")})
    assert forced.status_code == 200
    body = forced.json()
    assert body["id"] == original["id"]
    assert body["reprocessedExisting"] is True
    assert len(store.list()) == 1
    assert len(submitted) == 1
    assert submitted[0][1][0] == original["id"]


def test_reprocess_endpoint_marks_document_processing(monkeypatch):
    """POST /api/documents/{id}/reprocess - the Documents page's dedicated
    Reprocess button (distinct from the force=true upload-duplicate path
    above) had no direct test coverage; a user reported it failing live
    with a bare 500. Covers the happy path through the real endpoint."""
    _reset_store()
    client = TestClient(app)
    content = b"%PDF-1.4\n%reprocess-endpoint-fixture\n"
    doc = store.create("reprocess-me.pdf", content)
    submitted = []

    class ImmediateCaptureExecutor:
        def submit(self, fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            return None

    monkeypatch.setattr(app_module, "_executor", ImmediateCaptureExecutor())

    res = client.post(f"/api/documents/{doc['id']}/reprocess")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == doc["id"]
    assert body["status"] == "processing"
    assert len(submitted) == 1
    assert submitted[0][1][0] == doc["id"]


def test_reprocess_endpoint_missing_document_returns_404():
    _reset_store()
    client = TestClient(app)
    res = client.post("/api/documents/does-not-exist/reprocess")
    assert res.status_code == 404


def test_unhandled_exception_returns_diagnosable_json_not_bare_500(monkeypatch):
    """A real unhandled exception must not surface as Starlette's default
    opaque PlainTextResponse("Internal Server Error") - the frontend's
    error dialogs show that verbatim with nothing to act on (reported
    live via the Documents page's Reprocess button). The global handler
    in app.py should return the exception's own type/message as JSON
    instead, so a future failure is actually diagnosable."""
    _reset_store()
    client = TestClient(app, raise_server_exceptions=False)

    def _boom():
        raise RuntimeError("synthetic failure for test coverage")

    monkeypatch.setattr(app_module.store, "list", _boom)

    res = client.get("/api/documents")
    assert res.status_code == 500
    body = res.json()
    assert body["type"] == "RuntimeError"
    assert "synthetic failure" in body["message"]
