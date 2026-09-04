"""User report ("ตรวจเรื่องการอ่านเอกสาร"): a document uploaded weeks
earlier was still shown "กำลังประมวลผล" (processing) with no way to do
anything about it - confirmed live against the real app (a document
uploaded 2026-08-20 was still status='processing' on 2026-09-04).

Root cause: nothing ever recorded a server crash/restart mid-job - the
worker thread that was actually reading the PDF is gone with the old
process, but the DB row is left saying status='processing' forever. That
status is a dead end by the app's own design: try_start_processing()
(mark_reprocessing, called by both the Reprocess endpoint and the
force-upload-duplicate path) refuses to start a new run while
status='processing', and the Documents view hides the Reprocess button
and disables Remove for exactly that status - so the document could
never be reprocessed or deleted through the UI again.

DocumentStore.recover_interrupted_processing() (called once at API
startup, see app.py's startup handler) marks every still-'processing'
document 'error' with a clear, actionable message: this process hasn't
submitted any processing job yet at startup, so anything already
'processing' at that moment is unconditionally leftover from before the
restart, never a job actually running right now.
"""
from __future__ import annotations

from pdf_document_intelligence.api.store import DocumentStore
from pdf_document_intelligence.db.connection import open_independent_connection
from pdf_document_intelligence.db.repository import Repository


def _repo_at(db_path):
    return Repository(open_independent_connection(db_path))


def test_a_document_stuck_processing_is_recovered_to_error(tmp_path):
    repo = _repo_at(tmp_path / "app.db")
    repo.create_document("doc-1", sha256="a", filename="stuck.pdf", file_size=1)
    assert repo.get_document("doc-1")["status"] == "processing"

    recovered = DocumentStore(repo).recover_interrupted_processing()

    assert recovered == ["doc-1"]
    doc = repo.get_document("doc-1")
    assert doc["status"] == "error"
    assert doc["error"]  # a real, non-empty message - not silently blanked


def test_a_completed_document_is_left_untouched(tmp_path):
    repo = _repo_at(tmp_path / "app.db")
    repo.create_document("doc-1", sha256="a", filename="done.pdf", file_size=1)
    repo.set_document_complete("doc-1", 1, {"confidence": 0.97, "statusDocument": "AUTO_APPROVED", "reconciled": True})

    recovered = DocumentStore(repo).recover_interrupted_processing()

    assert recovered == []
    assert repo.get_document("doc-1")["status"] == "complete"


def test_an_already_errored_document_is_left_untouched(tmp_path):
    repo = _repo_at(tmp_path / "app.db")
    repo.create_document("doc-1", sha256="a", filename="broken.pdf", file_size=1)
    repo.set_document_error("doc-1", "PDF_CORRUPTED: some earlier real failure")

    recovered = DocumentStore(repo).recover_interrupted_processing()

    assert recovered == []
    doc = repo.get_document("doc-1")
    assert doc["status"] == "error"
    assert doc["error"] == "PDF_CORRUPTED: some earlier real failure"


def test_a_deleted_document_is_not_recovered(tmp_path):
    repo = _repo_at(tmp_path / "app.db")
    repo.create_document("doc-1", sha256="a", filename="stuck.pdf", file_size=1)
    repo.soft_delete_document("doc-1")

    recovered = DocumentStore(repo).recover_interrupted_processing()

    assert recovered == []


def test_the_recovered_document_can_be_reprocessed_afterward(tmp_path):
    """The whole point: mark_reprocessing() (try_start_processing) refuses
    to start a new run while status='processing' - confirming the fix
    actually unblocks Reprocess, not just that the status column changed."""
    repo = _repo_at(tmp_path / "app.db")
    repo.create_document("doc-1", sha256="a", filename="stuck.pdf", file_size=1)
    assert repo.try_start_processing("doc-1") is False  # stuck: refuses while already 'processing'

    DocumentStore(repo).recover_interrupted_processing()

    assert repo.try_start_processing("doc-1") is True  # unblocked
