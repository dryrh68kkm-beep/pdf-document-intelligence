"""Auto PDF Folder Import: InboxWatcher's scanning/stability/dedup logic,
exercised directly with fake find_any_by_sha256/ingest_new_file callbacks
(no FastAPI app, no real pipeline, no background thread/timer) so these
stay fast and deterministic. End-to-end wiring against the real app/store/
pipeline is covered separately in
tests/integration/test_inbox_folder_import.py.

hashlib.sha256 over plain bytes (not a real PDF structure) is enough here -
InboxWatcher itself never inspects PDF content, only bytes/size/mtime and
whatever find_any_by_sha256/ingest_new_file (both faked below) decide to do
with the hash.
"""
from __future__ import annotations

import hashlib
import threading
import time

from pdf_document_intelligence.api.inbox_watcher import InboxWatcher


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class _FakeCatalog:
    """Stands in for the `documents` table's sha256 column, active +
    soft-deleted rows combined - exactly what find_any_by_sha256 queries
    in the real repository."""

    def __init__(self) -> None:
        self.known: dict[str, dict] = {}
        self.find_calls: list[str] = []

    def find_any_by_sha256(self, sha256: str) -> dict | None:
        self.find_calls.append(sha256)
        return self.known.get(sha256)

    def mark_known(self, sha256: str, **fields) -> None:
        self.known[sha256] = {"sha256": sha256, **fields}


class _FakeIngestor:
    """Stands in for _ingest_inbox_file - records every call and lets a
    test script exactly what each call should return (a doc dict, or None
    to simulate a full processing queue / a lost sha256-race)."""

    def __init__(self, catalog: _FakeCatalog, admit: bool = True) -> None:
        self._catalog = catalog
        self._admit = admit
        self.calls: list[tuple[str, str, int, str]] = []

    def ingest(self, sha256: str, filename: str, file_size: int, source_path) -> dict | None:
        self.calls.append((sha256, filename, file_size, str(source_path)))
        if not self._admit:
            return None
        doc = {"id": f"doc-{len(self.calls)}", "sha256": sha256, "filename": filename}
        self._catalog.mark_known(sha256)
        return doc


def _watcher(inbox_dir, catalog: _FakeCatalog, ingestor: _FakeIngestor, stability_rounds: int = 2) -> InboxWatcher:
    return InboxWatcher(
        inbox_dir=inbox_dir,
        find_any_by_sha256=catalog.find_any_by_sha256,
        ingest_new_file=ingestor.ingest,
        stability_rounds=stability_rounds,
    )


def _write(path, data: bytes) -> None:
    path.write_bytes(data)


# 1. New PDF -> import once ---------------------------------------------

def test_a_new_stable_pdf_is_imported_after_two_stable_scans(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    _write(tmp_path / "a.pdf", b"%PDF-1.4 synthetic bytes")

    watcher.scan_once()  # round 1: first sighting, not yet stable
    assert ingestor.calls == []

    watcher.scan_once()  # round 2: unchanged since round 1 -> stable, imported
    assert len(ingestor.calls) == 1
    assert ingestor.calls[0][1] == "a.pdf"


# 2. Second scan -> no duplicate import ----------------------------------

def test_repeated_scans_of_an_already_imported_file_do_not_reimport(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    _write(tmp_path / "a.pdf", b"%PDF-1.4 synthetic bytes")

    for _ in range(5):
        watcher.scan_once()

    assert len(ingestor.calls) == 1


# 3. Restart -> already-imported file is not reprocessed -----------------

def test_a_fresh_watcher_instance_skips_a_file_already_known_to_the_catalog(tmp_path):
    """Simulates a server restart: a brand-new InboxWatcher (no in-memory
    state carried over) scanning a file whose sha256 the DB (here, the
    fake catalog) already has a row for from before the restart."""
    catalog = _FakeCatalog()
    data = b"%PDF-1.4 already imported before restart"
    catalog.mark_known(_sha256_bytes(data))
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    _write(tmp_path / "a.pdf", data)

    watcher.scan_once()
    watcher.scan_once()

    assert ingestor.calls == []


# 4. Rename but same hash -> skip ----------------------------------------

def test_renaming_a_file_with_unchanged_content_does_not_reimport_it(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    data = b"%PDF-1.4 same content different name"
    path = tmp_path / "original.pdf"
    _write(path, data)
    watcher.scan_once()
    watcher.scan_once()
    assert len(ingestor.calls) == 1

    path.rename(tmp_path / "renamed.pdf")
    watcher.scan_once()
    watcher.scan_once()

    # The sha256 is already known (from the first import under the old
    # name) - the renamed entry must resolve via find_any_by_sha256, not
    # trigger a second ingest.
    assert len(ingestor.calls) == 1


# 5. Same filename, new content -> process as new -------------------------

def test_same_filename_with_changed_content_is_imported_as_a_new_file(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    path = tmp_path / "a.pdf"
    _write(path, b"%PDF-1.4 version one")
    watcher.scan_once()
    watcher.scan_once()
    assert len(ingestor.calls) == 1

    time.sleep(0.01)
    _write(path, b"%PDF-1.4 version two, totally different bytes")
    watcher.scan_once()
    watcher.scan_once()

    assert len(ingestor.calls) == 2
    assert ingestor.calls[0][0] != ingestor.calls[1][0]  # different sha256


# 6. File still being copied -> defer -------------------------------------

def test_a_file_still_changing_size_is_never_imported_until_it_stabilizes(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    path = tmp_path / "a.pdf"

    _write(path, b"%PDF-1.4 partial")
    watcher.scan_once()
    assert ingestor.calls == []

    _write(path, b"%PDF-1.4 partial plus more bytes copied in")
    watcher.scan_once()  # size changed since last scan - stability restarts
    assert ingestor.calls == []

    _write(path, b"%PDF-1.4 partial plus more bytes copied in plus even more")
    watcher.scan_once()  # size changed again - this scan just records the new size, doesn't process it yet
    assert ingestor.calls == []

    # The copy has now finished - the next scan sees the same size/mtime as
    # the one just above, satisfying "at least 2 rounds unchanged".
    watcher.scan_once()
    assert len(ingestor.calls) == 1


# 7. Concurrent scans -> only one document ---------------------------------

def test_two_concurrent_scans_never_import_the_same_file_twice(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    _write(tmp_path / "a.pdf", b"%PDF-1.4 concurrent scan target")
    watcher.scan_once()  # first sighting

    barrier = threading.Barrier(2)

    def run():
        barrier.wait(timeout=5)
        for _ in range(3):
            watcher.scan_once()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(ingestor.calls) == 1


# 8. A sha256 already represented by *some* row (e.g. a manual upload) is
#    never re-ingested from the inbox --------------------------------------

def test_a_file_already_known_via_any_existing_row_is_never_ingested():
    """Whatever created the existing row (a manual Add Files upload, an
    earlier inbox import, or a soft-deleted document) is irrelevant to
    InboxWatcher - find_any_by_sha256 returning *anything* is the whole
    contract, matching Repository.find_any_document_by_sha256's own
    "active or not" reasoning."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        inbox_dir = Path(d)
        catalog = _FakeCatalog()
        data = b"%PDF-1.4 uploaded manually already"
        catalog.mark_known(_sha256_bytes(data))
        ingestor = _FakeIngestor(catalog)
        watcher = _watcher(inbox_dir, catalog, ingestor)
        _write(inbox_dir / "a.pdf", data)

        watcher.scan_once()
        watcher.scan_once()

        assert ingestor.calls == []


# 9. Queue full -> retry on a later scan, no duplicate ---------------------

def test_a_full_queue_is_retried_on_the_next_scan_without_duplicating(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog, admit=False)  # simulates create_document_if_below_processing_cap() returning None
    watcher = _watcher(tmp_path, catalog, ingestor)
    _write(tmp_path / "a.pdf", b"%PDF-1.4 queue is full right now")

    watcher.scan_once()
    watcher.scan_once()
    assert len(ingestor.calls) == 1  # attempted, but not admitted (ingestor returned None)

    watcher.scan_once()
    assert len(ingestor.calls) == 2  # retried on the next scan since it's still not resolved

    # Once the queue frees up and an attempt is actually admitted, no more
    # retries happen.
    ingestor._admit = True
    watcher.scan_once()
    admitted_calls = len(ingestor.calls)
    assert admitted_calls == 3
    watcher.scan_once()
    assert len(ingestor.calls) == admitted_calls


# 10. Delete -> not auto-resurrected ----------------------------------------

def test_a_previously_deleted_documents_sha256_is_never_reimported(tmp_path):
    """find_any_by_sha256 (unlike find_by_hash) deliberately does not
    filter out a soft-deleted document's row - that's the entire
    mechanism this feature uses to remember "the user removed this,
    leave it alone"."""
    catalog = _FakeCatalog()
    data = b"%PDF-1.4 user deleted this document earlier"
    catalog.mark_known(_sha256_bytes(data))  # simulates a soft-deleted row's sha256 still present
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    _write(tmp_path / "a.pdf", data)

    watcher.scan_once()
    watcher.scan_once()

    assert ingestor.calls == []


def test_scan_once_is_a_noop_when_the_inbox_directory_does_not_exist(tmp_path):
    watcher = _watcher(tmp_path / "does-not-exist", _FakeCatalog(), _FakeIngestor(_FakeCatalog()))
    watcher.scan_once()  # must not raise
    assert watcher.last_scan_at is not None


def test_a_non_pdf_file_in_the_inbox_is_ignored(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    _write(tmp_path / "readme.txt", b"not a pdf")

    watcher.scan_once()
    watcher.scan_once()

    assert ingestor.calls == []


def test_reset_for_tests_clears_bookkeeping_so_a_reused_filename_starts_fresh(tmp_path):
    catalog = _FakeCatalog()
    ingestor = _FakeIngestor(catalog)
    watcher = _watcher(tmp_path, catalog, ingestor)
    path = tmp_path / "a.pdf"
    _write(path, b"%PDF-1.4 first content")
    watcher.scan_once()
    watcher.scan_once()
    assert len(ingestor.calls) == 1

    watcher.reset_for_tests()
    assert watcher.last_scan_at is None
