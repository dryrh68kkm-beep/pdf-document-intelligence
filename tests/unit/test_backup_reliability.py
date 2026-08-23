from __future__ import annotations

import io
import sqlite3
import zipfile

import pytest

from pdf_document_intelligence.db import backup


def _minimal_connection():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE documents (id TEXT)")
    conn.execute("CREATE TABLE product_rows (id TEXT)")
    conn.execute("CREATE TABLE local_product_master (id TEXT)")
    return conn


def test_same_second_backups_get_unique_names_and_leave_no_snapshot(tmp_path, monkeypatch):
    conn = _minimal_connection()
    suffixes = iter(["aaaaaaaa", "bbbbbbbb"])
    monkeypatch.setattr(backup, "get_connection", lambda: conn)
    monkeypatch.setattr(backup, "current_version", lambda _conn: 1)
    monkeypatch.setattr(backup, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(backup, "_timestamp", lambda: "20260823-120000")
    monkeypatch.setattr(backup, "_unique_suffix", lambda: next(suffixes))

    first = backup.create_backup()
    second = backup.create_backup()

    assert first != second
    assert first.exists() and second.exists()
    assert list((tmp_path / "backups").glob("_snapshot-*.db")) == []


def test_failed_backup_write_cleans_snapshot(tmp_path, monkeypatch):
    conn = _minimal_connection()
    monkeypatch.setattr(backup, "get_connection", lambda: conn)
    monkeypatch.setattr(backup, "current_version", lambda _conn: 1)
    monkeypatch.setattr(backup, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(backup, "_timestamp", lambda: "20260823-120000")
    monkeypatch.setattr(backup, "_unique_suffix", lambda: "deadbeef")

    class BrokenZip:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("simulated zip failure")

    monkeypatch.setattr(backup.zipfile, "ZipFile", BrokenZip)

    with pytest.raises(RuntimeError, match="simulated zip failure"):
        backup.create_backup()

    assert list((tmp_path / "backups").glob("_snapshot-*.db")) == []


def test_invalid_restore_cleans_candidate_file(tmp_path, monkeypatch):
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("app.db", b"not-a-real-sqlite-db")

    monkeypatch.setattr(backup, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(backup, "_timestamp", lambda: "20260823-120000")
    monkeypatch.setattr(backup, "_unique_suffix", lambda: "cafebabe")

    def invalid_version(_conn):
        raise sqlite3.DatabaseError("invalid database")

    monkeypatch.setattr(backup, "current_version", invalid_version)

    with pytest.raises(backup.RestoreError, match="not a valid database"):
        backup.restore_backup(payload.getvalue())

    assert list(tmp_path.glob("_restore-candidate-*.db")) == []
