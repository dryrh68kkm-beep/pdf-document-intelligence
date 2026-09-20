"""Auto PDF Folder Import, end-to-end against the real app/store/pipeline:
a synthetic PDF dropped into data/inbox is picked up, deduped against
`documents` (any status, active or soft-deleted) exactly the way a manual
"Add Files" upload is, and fed through the real processing pipeline - no
mocked OCR/parser, no fake store. Pure scanning/stability/dedup logic
(fake callbacks, no real pipeline) is covered separately in
tests/unit/test_inbox_watcher.py; this file is the "does the real wiring
actually work" complement.

inbox_watcher.scan_once() is called directly rather than through
inbox_watcher.start()'s background thread - matching this suite's existing
convention of not exercising app.py's lifespan (see e.g.
test_recover_interrupted_processing.py, which tests DocumentStore's method
directly rather than via a running server's startup hook), and keeping
these tests free of any real sleep/timing dependency.
"""
from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pdf_document_intelligence.api.app import _ingest_inbox_file, app, inbox_watcher
from pdf_document_intelligence.api.inbox_watcher import InboxWatcher
from pdf_document_intelligence.api.store import store
from tests.synthetic_documents import make_bigc_pdf


@pytest.fixture(autouse=True)
def _isolated_inbox():
    store.reset_for_tests()
    inbox_watcher.reset_for_tests()
    yield
    # The real ingest path COPIES a file out of the inbox (never moves or
    # deletes the user's original) - clean up whatever this test dropped
    # into the real, session-shared inbox directory so later tests start
    # from an empty folder.
    for leftover in inbox_watcher.inbox_dir.glob("*.pdf"):
        leftover.unlink(missing_ok=True)
    inbox_watcher.reset_for_tests()


def _wait_complete(client: TestClient, doc_id: str, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] in ("complete", "error"):
            return doc
        time.sleep(1)
    raise TimeoutError("document did not finish processing in time")


def _drop_into_inbox(tmp_path: Path, filename: str) -> Path:
    source = make_bigc_pdf(tmp_path / filename)
    dest = inbox_watcher.inbox_dir / filename
    shutil.copy2(str(source), str(dest))
    return dest


def _stabilize(rounds: int = 3) -> None:
    for _ in range(rounds):
        inbox_watcher.scan_once()


def test_a_new_pdf_dropped_into_inbox_is_imported_once(tmp_path):
    client = TestClient(app)
    _drop_into_inbox(tmp_path, "inbox-a.pdf")

    _stabilize()

    docs = store.list()
    assert len(docs) == 1
    doc = _wait_complete(client, docs[0]["id"])
    assert doc["status"] == "complete"


def test_a_second_scan_of_an_already_imported_file_does_not_reimport(tmp_path):
    client = TestClient(app)
    _drop_into_inbox(tmp_path, "inbox-b.pdf")
    _stabilize()
    docs = store.list()
    assert len(docs) == 1
    _wait_complete(client, docs[0]["id"])

    for _ in range(5):
        inbox_watcher.scan_once()

    assert len(store.list()) == 1


def test_restart_does_not_reprocess_an_already_imported_file(tmp_path):
    """Simulates a server restart: a brand-new InboxWatcher instance (no
    in-memory bookkeeping carried over, matching a real process restart)
    wired to the same real store and the same real ingest pipeline."""
    client = TestClient(app)
    _drop_into_inbox(tmp_path, "inbox-c.pdf")
    _stabilize()
    docs = store.list()
    assert len(docs) == 1
    _wait_complete(client, docs[0]["id"])

    fresh_watcher = InboxWatcher(
        inbox_dir=inbox_watcher.inbox_dir,
        find_any_by_sha256=store.find_any_by_hash,
        ingest_new_file=_ingest_inbox_file,
    )
    fresh_watcher.scan_once()
    fresh_watcher.scan_once()

    assert len(store.list()) == 1


def test_manual_upload_and_an_inbox_copy_of_the_same_pdf_do_not_duplicate(tmp_path):
    client = TestClient(app)
    source = make_bigc_pdf(tmp_path / "same.pdf")

    with source.open("rb") as f:
        res = client.post("/api/documents", files={"file": ("same.pdf", f, "application/pdf")})
    assert res.status_code == 200
    manual_doc = _wait_complete(client, res.json()["id"])
    assert manual_doc["status"] == "complete"

    shutil.copy2(str(source), str(inbox_watcher.inbox_dir / "same.pdf"))
    _stabilize()

    assert len(store.list()) == 1


def test_deleting_a_document_does_not_resurrect_it_from_the_inbox(tmp_path):
    client = TestClient(app)
    _drop_into_inbox(tmp_path, "inbox-d.pdf")
    _stabilize()
    docs = store.list()
    assert len(docs) == 1
    doc = _wait_complete(client, docs[0]["id"])
    assert doc["status"] == "complete"

    res = client.delete(f"/api/documents/{doc['id']}")
    assert res.status_code == 200
    assert store.list() == []

    # The original file the user dropped in is still sitting in
    # data/inbox untouched - further scans must never bring the deleted
    # document back.
    for _ in range(5):
        inbox_watcher.scan_once()

    assert store.list() == []


def test_manual_reprocess_still_works_on_an_inbox_imported_document(tmp_path):
    client = TestClient(app)
    _drop_into_inbox(tmp_path, "inbox-e.pdf")
    _stabilize()
    docs = store.list()
    assert len(docs) == 1
    doc = _wait_complete(client, docs[0]["id"])
    assert doc["status"] == "complete"

    res = client.post(f"/api/documents/{doc['id']}/reprocess")
    assert res.status_code == 200
    reprocessed = _wait_complete(client, doc["id"])
    assert reprocessed["status"] == "complete"


def test_inbox_status_endpoint_does_not_expose_absolute_server_path():
    client = TestClient(app)
    res = client.get("/api/inbox/status")
    assert res.status_code == 200
    body = res.json()
    assert body["folder"] == inbox_watcher.inbox_dir.name
    assert str(inbox_watcher.inbox_dir) not in body["folder"]
    assert "watching" in body
    assert "customFolder" in body
    assert "lastScanAt" in body
    assert "lastError" in body


def test_inbox_ingest_rejects_source_changed_after_watcher_hash(tmp_path):
    """TOCTOU regression: the watcher hashes a stable source, but another
    process replaces it before app.py copies it. The DB must never store the
    old SHA for the new bytes."""
    source = make_bigc_pdf(tmp_path / "race.pdf")
    original = source.read_bytes()
    expected_hash = hashlib.sha256(original).hexdigest()
    expected_size = len(original)

    # Keep a valid PDF signature but change the bytes after the hash was
    # computed, matching the real race window between watcher and copy.
    source.write_bytes(original + b"\n%changed-after-hash")

    before_docs = len(store.list())
    managed_dir = inbox_watcher.inbox_dir.parent / "pdfs"
    before_files = set(managed_dir.glob("*.pdf")) if managed_dir.is_dir() else set()

    result = _ingest_inbox_file(expected_hash, "race.pdf", expected_size, source)

    assert result is None
    assert len(store.list()) == before_docs
    after_files = set(managed_dir.glob("*.pdf")) if managed_dir.is_dir() else set()
    assert after_files == before_files
