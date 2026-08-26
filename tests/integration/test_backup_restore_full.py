"""PR2: full backup/restore - DB + PDFs + master catalog snapshot in one
archive, not just the DB. Exercises the real create_backup()/restore_backup()
against an isolated data directory (never the shared session one from
tests/conftest.py - restore_backup() closes and reopens the global DB
connection singleton, which every other test in the session also depends
on) via db.connection.reset_connection_for_tests, restored to the shared
directory again on teardown.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from pdf_document_intelligence.db import backup
from pdf_document_intelligence.db import connection as connection_module
from pdf_document_intelligence.db.paths import get_pdf_path
from tests.unit.db_helpers import make_result, make_row


@pytest.fixture()
def isolated_data_dir(tmp_path, monkeypatch):
    """Points the real DB singleton and PDF_INTELLIGENCE_DATA_DIR at a
    throwaway directory for the duration of one test - restore_backup()
    closes and reopens the global connection singleton, which the shared
    session data dir (tests/conftest.py) must not have happen to it mid
    test-run. Reopens the singleton against the shared directory again on
    teardown (the file on disk is untouched by anything this test does;
    only the isolated copy is ever swapped)."""
    from pdf_document_intelligence.db.paths import get_data_dir as _shared_get_data_dir

    shared_data_dir = _shared_get_data_dir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(data_dir))
    connection_module.reset_connection_for_tests(data_dir / "app.db")
    try:
        yield data_dir
    finally:
        connection_module.reset_connection_for_tests(shared_data_dir / "app.db")


def _repo():
    from pdf_document_intelligence.api.store import store

    return store.repo


def _make_document_with_pdf(pdf_bytes: bytes = b"%PDF-1.4\n%synthetic\n"):
    from pdf_document_intelligence.api.store import store

    doc = store.create("t.pdf", pdf_bytes)
    rows = [make_row(0, "BAKERY", "8850000000001", "ART1", "Test Product", 5.0, 1, 10)]
    result = make_result(doc["id"], "t.pdf", [("BAKERY", rows)])
    store.set_complete(doc["id"], result)
    return doc


def test_full_backup_contains_db_pdf_master_and_metadata(isolated_data_dir):
    from pdf_document_intelligence.catalog.loader import get_default_catalog
    from pdf_document_intelligence.catalog.snapshot import import_catalog_snapshot

    doc = _make_document_with_pdf()

    catalog_csv = isolated_data_dir / "external_master.csv"
    catalog_csv.write_text(
        "BARCODE,ART_SV_NAME,SUBCLASS_NAME,ART_NO,DEPARTMENT_NAME,DIVISION_NAME,CURRENT_COST\n"
        "8850000000001,Test Product,SUB,ART1,BAKERY,04 DRY FOOD,12.50\n",
        encoding="utf-8",
    )
    import_catalog_snapshot(catalog_csv, overwrite=True)
    get_default_catalog.cache_clear()

    zip_path = backup.create_backup()
    assert zip_path.exists()

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "app.db" in names
        assert f"pdfs/{doc['id']}.pdf" in names
        assert "master_catalog.snapshot.json" in names
        assert "metadata.json" in names

        metadata = json.loads(zf.read("metadata.json"))
        assert metadata["backupFormatVersion"] == 2
        assert metadata["appVersion"]
        assert metadata["pdfCount"] == 1
        assert metadata["hasMasterSnapshot"] is True
        assert metadata["counts"]["documents"] == 1

        import hashlib

        for member in names - {"metadata.json"}:
            expected = metadata["checksums"][member]
            assert hashlib.sha256(zf.read(member)).hexdigest() == expected


def _build_zip(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_checksum_mismatch_rejects_restore(isolated_data_dir):
    doc = _make_document_with_pdf()
    zip_bytes = backup.create_backup().read_bytes()

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        metadata = json.loads(zf.read("metadata.json"))
        app_db = zf.read("app.db")
        pdf_member = f"pdfs/{doc['id']}.pdf"
        pdf_bytes = zf.read(pdf_member)

    # Tamper with the PDF payload without updating its checksum.
    tampered = _build_zip({"app.db": app_db, pdf_member: pdf_bytes + b"\ntampered", "metadata.json": json.dumps(metadata).encode()})

    with pytest.raises(backup.RestoreError, match="checksum mismatch"):
        backup.restore_backup(tampered)


def test_path_traversal_entry_rejects_restore(isolated_data_dir):
    zip_bytes = backup.create_backup().read_bytes()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        app_db = zf.read("app.db")
        metadata = zf.read("metadata.json")

    malicious = _build_zip(
        {
            "app.db": app_db,
            "metadata.json": metadata,
            "../../etc/evil.pdf": b"not-a-pdf",
        }
    )

    with pytest.raises(backup.RestoreError, match="unexpected entry"):
        backup.restore_backup(malicious)


def test_corrupt_db_rejects_restore(isolated_data_dir):
    bad_db = b"not-a-real-sqlite-db"
    import hashlib

    metadata = {
        "backupFormatVersion": 2,
        "checksums": {"app.db": hashlib.sha256(bad_db).hexdigest()},
    }
    payload = _build_zip({"app.db": bad_db, "metadata.json": json.dumps(metadata).encode()})

    with pytest.raises(backup.RestoreError, match="not a valid database"):
        backup.restore_backup(payload)


def test_legacy_db_only_backup_restores_without_claiming_full_restore(isolated_data_dir):
    """A backup made before this format existed (or by another tool) is
    just app.db + no metadata (or old-shaped metadata) - still restorable,
    but must say so rather than claiming PDFs/master snapshot came along."""
    _make_document_with_pdf()
    full_backup = backup.create_backup().read_bytes()
    with zipfile.ZipFile(io.BytesIO(full_backup)) as zf:
        app_db = zf.read("app.db")

    legacy_zip = _build_zip({"app.db": app_db})

    result = backup.restore_backup(legacy_zip)
    assert result["restored"] is True
    assert result["legacy"] is True
    assert result["pdfsRestored"] == 0
    assert result["masterSnapshotRestored"] is False


def test_restored_pdf_bytes_match_original(isolated_data_dir):
    pdf_bytes = b"%PDF-1.4\n%round-trip-fixture\n" + b"x" * 1000
    doc = _make_document_with_pdf(pdf_bytes)

    zip_bytes = backup.create_backup().read_bytes()
    # Simulate data loss, then restore.
    get_pdf_path(doc["id"]).unlink()

    result = backup.restore_backup(zip_bytes)
    assert result["pdfsRestored"] == 1
    assert result["missingPdfCount"] == 0
    assert get_pdf_path(doc["id"]).read_bytes() == pdf_bytes


def test_failed_restore_preserves_original_installation(isolated_data_dir, monkeypatch):
    doc = _make_document_with_pdf()
    zip_bytes = backup.create_backup().read_bytes()

    def _boom(*args, **kwargs):
        raise OSError("simulated disk failure swapping the DB file")

    # The DB swap (shutil.move) is deliberately the *last* step in
    # restore_backup() - PDFs and the master snapshot are staged first, so
    # a failure here proves the ordering actually protects the DB: it must
    # still hold the original data even though other files were already
    # written. (A raw byte-for-byte comparison of app.db isn't meaningful
    # here - closing/reopening a WAL-mode connection can rewrite header
    # counters via a checkpoint with no logical data change, so this checks
    # the data itself instead.)
    monkeypatch.setattr(backup.shutil, "move", _boom)

    with pytest.raises(OSError, match="simulated disk failure"):
        backup.restore_backup(zip_bytes)

    monkeypatch.undo()
    from pdf_document_intelligence.db.connection import get_connection

    get_connection()  # the singleton was closed and set to None before the
    # simulated failure - reopen it the same way a real server would after
    # a crashed restore, to confirm the original file is still intact.
    restored = _repo().get_document(doc["id"])
    assert restored is not None
    assert restored["filename"] == "t.pdf"


def test_restore_via_api_clears_catalog_caches_so_new_snapshot_resolves(isolated_data_dir):
    """The catalog/department readers are lru_cache'd for the life of the
    process (see app.py's _clear_catalog_caches) - restoring a backup that
    carries a *different* master_catalog.snapshot.json must invalidate
    that cache the same way a live master import already does, or a
    barcode lookup right after restore keeps resolving against whatever
    catalog happened to be in memory before the restore, not the one that
    was just restored to disk."""
    from fastapi.testclient import TestClient

    from pdf_document_intelligence.api.app import app
    from pdf_document_intelligence.catalog.loader import get_default_catalog

    client = TestClient(app)

    def _import_catalog_csv(cost: str):
        csv_bytes = (
            "BARCODE,ART_SV_NAME,SUBCLASS_NAME,ART_NO,DEPARTMENT_NAME,DIVISION_NAME,CURRENT_COST\n"
            f"8850000000001,Test Product,SUB,ART1,BAKERY,04 DRY FOOD,{cost}\n"
        ).encode()
        res = client.post("/api/master/import", files={"file": ("m.csv", csv_bytes, "text/csv")})
        assert res.status_code == 200

    _import_catalog_csv("10.00")
    get_default_catalog()  # warm the cache, as a real request would
    assert get_default_catalog()["8850000000001"].unit_cost == 10

    backup_res = client.post("/api/backup")
    assert backup_res.status_code == 200
    zip_bytes = backup_res.content

    _import_catalog_csv("99.00")  # live import already clears the cache
    assert get_default_catalog()["8850000000001"].unit_cost == 99

    restore_res = client.post("/api/restore", files={"file": ("b.zip", zip_bytes, "application/zip")})
    assert restore_res.status_code == 200
    assert restore_res.json()["masterSnapshotRestored"] is True

    # If the cache weren't cleared, this would still read 99.
    assert get_default_catalog()["8850000000001"].unit_cost == 10


def test_restore_rejected_while_a_document_is_processing(isolated_data_dir):
    """PR3: restore must not run concurrently with an in-flight OCR job -
    a document freshly created via store.create() is 'processing' by
    default (no store.set_complete() call here) until a background job
    marks it otherwise."""
    from pdf_document_intelligence.api.store import store

    zip_bytes = backup.create_backup().read_bytes()  # valid backup of an empty install
    doc = store.create("mid-flight.pdf", b"%PDF-1.4\n%still-processing\n")

    with pytest.raises(backup.RestoreConflictError, match="processing"):
        backup.restore_backup(zip_bytes)
    # A rejected restore must be a true no-op - the document is still
    # exactly as it was, still processing.
    assert _repo().get_document(doc["id"])["status"] == "processing"


def test_restore_allowed_once_processing_completes(isolated_data_dir):
    """The same document that blocked restore above must no longer block
    it once it reaches a terminal status (complete/error) - restore isn't
    permanently stuck, only blocked while something is genuinely in
    flight."""
    doc = _make_document_with_pdf()  # store.set_complete() inside this helper
    zip_bytes = backup.create_backup().read_bytes()

    result = backup.restore_backup(zip_bytes)
    assert result["restored"] is True
    assert _repo().get_document(doc["id"]) is not None


def test_restore_endpoint_returns_423_while_processing(isolated_data_dir):
    """API-level: the fast up-front check in app.py's /api/restore returns
    423 (not 409 - api.js's json() helper treats 409 as a non-error
    special case for the upload-duplicate flow) without even reading the
    uploaded archive."""
    from fastapi.testclient import TestClient

    from pdf_document_intelligence.api.app import app
    from pdf_document_intelligence.api.store import store

    client = TestClient(app)
    store.create("mid-flight.pdf", b"%PDF-1.4\n%still-processing\n")

    zip_bytes = backup.create_backup().read_bytes()
    res = client.post("/api/restore", files={"file": ("b.zip", zip_bytes, "application/zip")})
    assert res.status_code == 423
