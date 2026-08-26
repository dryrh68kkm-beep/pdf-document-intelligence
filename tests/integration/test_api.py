"""Fast API wiring tests - deliberately avoid uploading a real PDF here
(that's a ~65s round trip through the full OCR pipeline, already covered
by test_golden_regression.py via the orchestrator directly). These just
confirm the FastAPI app boots, routes correctly, and the store starts
empty - endpoint plumbing, not extraction correctness.
"""
from __future__ import annotations

import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import pdf_document_intelligence.api.app as app_module
from pdf_document_intelligence.api.app import app
from pdf_document_intelligence.api.store import store
from pdf_document_intelligence.db.paths import get_pdf_path
from tests.unit.db_helpers import make_result, make_row


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
    in app.py returns a diagnostic ID plus a generic message as JSON
    instead: actionable (the ID matches a traceback in the server log)
    without ever handing the client the raw exception message, which can
    contain file paths, SQL fragments, or other server internals (PR7)."""
    _reset_store()
    client = TestClient(app, raise_server_exceptions=False)

    def _boom():
        raise RuntimeError("synthetic failure for test coverage")

    monkeypatch.setattr(app_module.store, "list", _boom)

    res = client.get("/api/documents")
    assert res.status_code == 500
    body = res.json()
    assert body["type"] == "RuntimeError"
    assert re.match(r"^ERR-[0-9A-F]{8}$", body["diagnosticId"])
    # The raw exception message must never reach the client - only the
    # server-side log (asserted separately below) gets the real detail.
    assert "synthetic failure" not in body["message"]


def test_unhandled_exception_diagnostic_id_is_logged_with_traceback(monkeypatch, caplog):
    """The diagnostic ID returned to the client must be findable in the
    server log, alongside the real exception detail that was deliberately
    kept out of the HTTP response."""
    import logging

    _reset_store()
    client = TestClient(app, raise_server_exceptions=False)

    def _boom():
        raise RuntimeError("synthetic failure for log coverage")

    monkeypatch.setattr(app_module.store, "list", _boom)

    with caplog.at_level(logging.ERROR, logger="pdf_document_intelligence"):
        res = client.get("/api/documents")

    diagnostic_id = res.json()["diagnosticId"]
    logged = "\n".join(record.getMessage() for record in caplog.records)
    assert diagnostic_id in logged
    assert "synthetic failure for log coverage" in caplog.text


def test_background_processing_failure_logs_diagnostic_id_and_stage(monkeypatch, caplog):
    """_run_processing runs on a worker thread, outside the request/response
    cycle the global exception_handler covers - it needs its own diagnostic
    ID + traceback logging so a background OCR/parse crash is just as
    traceable as a request-cycle one. The document's own `error` field must
    still carry the plain message (meaningful, user-facing info about *this
    file*, not an internal leak) - the diagnostic ID is a log-only addition,
    not a replacement for it."""
    import logging

    _reset_store()
    doc = store.create("boom.pdf", b"%PDF-1.4\n%background-failure-fixture\n")

    def _boom(pdf_path, *, settings, on_progress):
        on_progress("extract", 1, 3)
        raise ValueError("synthetic pipeline failure")

    monkeypatch.setattr(app_module, "process_document", _boom)

    with caplog.at_level(logging.ERROR, logger="pdf_document_intelligence"):
        app_module._run_processing(doc["id"])

    updated = store.get(doc["id"])
    assert updated["status"] == "error"
    assert updated["error"] == "synthetic pipeline failure"

    assert re.search(r"ERR-[0-9A-F]{8}", caplog.text)
    assert "synthetic pipeline failure" in caplog.text
    assert doc["id"] in caplog.text
    assert "extract" in caplog.text


def test_preflight_rejected_upload_marks_document_error_not_complete():
    """PR8: a real preflight rejection (corrupted PDF) must land the
    document in status='error' with the specific preflight code visible in
    the message - not status='complete' with a fake empty result, which is
    what process_document() used to silently return for this case."""
    _reset_store()
    doc = store.create("corrupted.pdf", b"%PDF-1.4\n" + b"\x00\x01\x02 not a real pdf body at all" * 20)

    app_module._run_processing(doc["id"])

    updated = store.get(doc["id"])
    assert updated["status"] == "error"
    assert updated["error"].startswith("PDF_CORRUPTED:")


def _complete_with_one_row(doc_id: str):
    """Drive a document to status='complete' with one real product row,
    without a PDF/OCR round trip - mirrors the pattern already used by
    tests/unit/test_persistence.py for exercising the persistence layer."""
    rows = [make_row(0, "BAKERY", "8850000000001", "ART1", "Test Product", 5.0, 1, 10)]
    result = make_result(doc_id, "t.pdf", [("BAKERY", rows)])
    store.set_complete(doc_id, result)
    row_id = store.repo.list_product_rows(document_id=doc_id)[0]["id"]
    return row_id


def test_delete_document_purges_pdf_file_from_disk():
    _reset_store()
    doc = store.create("purge-me.pdf", b"%PDF-1.4\n%purge-fixture\n")
    _complete_with_one_row(doc["id"])
    pdf_path = get_pdf_path(doc["id"])
    assert pdf_path.exists()

    client = TestClient(app)
    res = client.delete(f"/api/documents/{doc['id']}")
    assert res.status_code == 200
    assert not pdf_path.exists()


def test_deleted_document_detail_pdf_reprocess_and_row_all_404():
    _reset_store()
    doc = store.create("delete-me.pdf", b"%PDF-1.4\n%delete-fixture\n")
    row_id = _complete_with_one_row(doc["id"])
    client = TestClient(app)

    assert client.get(f"/api/products/{row_id}").status_code == 200

    res = client.delete(f"/api/documents/{doc['id']}")
    assert res.status_code == 200

    assert client.get(f"/api/documents/{doc['id']}").status_code == 404
    assert client.get(f"/api/documents/{doc['id']}/pdf").status_code == 404
    assert client.post(f"/api/documents/{doc['id']}/reprocess").status_code == 404
    assert client.get(f"/api/products/{row_id}").status_code == 404
    assert client.patch(f"/api/products/{row_id}", json={"field": "name", "value": "x"}).status_code == 404
    assert client.get(f"/api/products/{row_id}/history").status_code == 404
    # Deleting an already-deleted document must not look like success.
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 404


def test_delete_missing_physical_pdf_does_not_crash():
    """Item 7 of PR1: the file can already be gone (manual cleanup, a
    prior partial failure, ...) - the delete flow must still succeed and
    leave the DB in a clean deleted state instead of crashing."""
    _reset_store()
    doc = store.create("already-missing.pdf", b"%PDF-1.4\n%missing-fixture\n")
    _complete_with_one_row(doc["id"])
    get_pdf_path(doc["id"]).unlink()

    client = TestClient(app)
    res = client.delete(f"/api/documents/{doc['id']}")
    assert res.status_code == 200
    assert client.get(f"/api/documents/{doc['id']}").status_code == 404


def test_delete_document_while_processing_is_rejected(monkeypatch):
    """A document mid-OCR must not be deletable out from under the
    background job - rejected with 423 (not 409: api.js's json() helper
    treats 409 as a non-error special case for the upload-duplicate flow,
    which would make this rejection silently look like success)."""
    _reset_store()
    doc = store.create("still-processing.pdf", b"%PDF-1.4\n%processing-fixture\n")
    assert doc["status"] == "processing"

    client = TestClient(app)
    res = client.delete(f"/api/documents/{doc['id']}")
    assert res.status_code == 423
    # Rejected, not silently deleted - the document is still there.
    assert client.get(f"/api/documents/{doc['id']}").status_code == 200
    assert get_pdf_path(doc["id"]).exists()


def test_local_verified_master_survives_document_deletion():
    """Local Verified Master is global product knowledge keyed by
    barcode, not per-document data - deleting the document that first
    taught the system a barcode's name must not un-teach it."""
    _reset_store()
    doc = store.create("teaches-master.pdf", b"%PDF-1.4\n%master-fixture\n")
    row_id = _complete_with_one_row(doc["id"])
    client = TestClient(app)
    res = client.patch(f"/api/products/{row_id}", json={"field": "name", "value": "Corrected Name"})
    assert res.status_code == 200

    assert client.delete(f"/api/documents/{doc['id']}").status_code == 200

    entries = store.repo.list_local_master()
    assert any(e["barcode"] == "8850000000001" and e["product_name"] == "Corrected Name" for e in entries)


# ---- PR5: streaming upload / processing memory + queue ----


def test_upload_streams_to_disk_worker_reads_from_path(monkeypatch):
    """The background worker must operate on the file already sitting at
    its permanent path, not bytes handed across the thread boundary -
    _run_processing now takes only a doc_id."""
    _reset_store()
    client = TestClient(app)
    submitted = []

    class ImmediateCaptureExecutor:
        def submit(self, fn, *args, **kwargs):
            submitted.append((fn, args, kwargs))
            return None

    monkeypatch.setattr(app_module, "_executor", ImmediateCaptureExecutor())

    content = b"%PDF-1.4\n%pr5-stream-fixture\n"
    res = client.post("/api/documents", files={"file": ("stream.pdf", content, "application/pdf")})
    assert res.status_code == 200
    doc_id = res.json()["id"]

    assert len(submitted) == 1
    fn, args, kwargs = submitted[0]
    assert fn is app_module._run_processing
    assert args == (doc_id,)  # no pdf_bytes argument anymore
    # The file is already at its permanent location, readable by the path
    # _run_processing itself derives from doc_id (get_pdf_path).
    assert get_pdf_path(doc_id).read_bytes() == content


def test_oversized_upload_rejected_mid_stream_not_after_full_buffer(monkeypatch):
    """>max_file_size_bytes is rejected as soon as the stream crosses the
    limit - simulated with a tiny limit so the test doesn't need an
    actual 200MB+ file. No document/PDF file must be left behind."""
    _reset_store()
    monkeypatch.setattr(app_module._settings, "max_file_size_bytes", 10)
    client = TestClient(app)

    content = b"%PDF-1.4\n" + b"x" * 100  # well over the 10-byte limit
    res = client.post("/api/documents", files={"file": ("big.pdf", content, "application/pdf")})
    assert res.status_code == 400
    assert "too large" in res.json()["detail"].lower()
    assert store.list() == []


def test_upload_missing_pdf_magic_header_rejected():
    _reset_store()
    client = TestClient(app)
    # Extension says .pdf, content does not start with %PDF- - the
    # extension check alone (pre-existing) would have let this through.
    res = client.post("/api/documents", files={"file": ("fake.pdf", b"not a real pdf file", "application/pdf")})
    assert res.status_code == 400
    assert store.list() == []


def test_no_orphan_pdf_file_left_when_db_insert_fails(monkeypatch):
    """If Repository.create_document() raises for a reason unrelated to
    the known concurrent-duplicate race, the just-moved PDF file at the
    fresh doc_id's path must not be left behind with no DB row pointing
    at it."""
    _reset_store()
    client = TestClient(app, raise_server_exceptions=False)

    def _boom(*args, **kwargs):
        raise sqlite3.DatabaseError("simulated unrelated DB failure")

    monkeypatch.setattr(store.repo, "create_document", _boom)

    pdfs_dir = get_pdf_path("x").parent
    before = set(pdfs_dir.glob("*.pdf"))

    content = b"%PDF-1.4\n%pr5-orphan-fixture\n"
    res = client.post("/api/documents", files={"file": ("orphan.pdf", content, "application/pdf")})
    assert res.status_code == 500  # unrelated DB error - not the known duplicate-race message
    # No new PDF file left behind for this failed attempt - not asserting
    # the whole directory is empty, since other tests in this session may
    # have legitimately left their own (DB-tracked) PDFs there.
    assert set(pdfs_dir.glob("*.pdf")) == before


def test_queue_full_returns_503_without_crashing(monkeypatch):
    """A backlog of already-processing documents must produce a clear,
    controlled rejection instead of silently queueing forever or crashing."""
    _reset_store()
    monkeypatch.setattr(app_module, "_MAX_QUEUED_PROCESSING_JOBS", 1)
    store.create("already-processing.pdf", b"%PDF-1.4\n%queue-fixture\n")  # status='processing' by default

    client = TestClient(app)
    content = b"%PDF-1.4\n%pr5-queue-full-fixture\n"
    res = client.post("/api/documents", files={"file": ("overflow.pdf", content, "application/pdf")})
    assert res.status_code == 503
    # Rejected before any file was ever streamed to disk for this request.
    assert len(store.list()) == 1


def test_duplicate_detection_still_works_via_streamed_hash(monkeypatch):
    _reset_store()
    client = TestClient(app)
    content = b"%PDF-1.4\n%pr5-dup-fixture\n"

    first = client.post("/api/documents", files={"file": ("a.pdf", content, "application/pdf")})
    assert first.status_code == 200

    second = client.post("/api/documents", files={"file": ("b.pdf", content, "application/pdf")})
    assert second.status_code == 409
    assert second.json()["existingDocument"]["id"] == first.json()["id"]
