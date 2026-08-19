"""Backup/restore for the local SQLite database (spec P6 §24-26).

A backup is a zip containing a consistent snapshot of app.db (taken via
SQLite's own backup API, so it's safe even while the server is running)
plus a small metadata.json. Restore validates the schema version, backs
up the *current* DB first (so a bad restore is itself undoable), then
swaps the file in place.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from pdf_document_intelligence.db.connection import get_connection
from pdf_document_intelligence.db.migrations import SCHEMA_VERSION, current_version
from pdf_document_intelligence.db.paths import get_data_dir, get_db_path


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def create_backup() -> Path:
    conn = get_connection()
    version = current_version(conn)

    data_dir = get_data_dir()
    backups_dir = data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = backups_dir / f"_snapshot-{_timestamp()}.db"
    dest_conn = sqlite3.connect(str(snapshot_path))
    with dest_conn:
        conn.backup(dest_conn)
    dest_conn.close()

    counts = {
        "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
        "productRows": conn.execute("SELECT COUNT(*) FROM product_rows").fetchone()[0],
        "localMaster": conn.execute("SELECT COUNT(*) FROM local_product_master").fetchone()[0],
    }
    metadata = {
        "schemaVersion": version,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "counts": counts,
    }

    zip_path = backups_dir / f"backup-{_timestamp()}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(snapshot_path, "app.db")
        zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    snapshot_path.unlink(missing_ok=True)
    return zip_path


class RestoreError(Exception):
    pass


def restore_backup(zip_bytes: bytes) -> dict:
    import io

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if "app.db" not in names:
            raise RestoreError("backup zip missing app.db")
        metadata = json.loads(zf.read("metadata.json")) if "metadata.json" in names else {}
        db_bytes = zf.read("app.db")

    tmp_path = get_data_dir() / f"_restore-candidate-{_timestamp()}.db"
    tmp_path.write_bytes(db_bytes)
    try:
        candidate_conn = sqlite3.connect(str(tmp_path))
        candidate_version = current_version(candidate_conn)
        candidate_conn.close()
    except sqlite3.Error as exc:
        tmp_path.unlink(missing_ok=True)
        raise RestoreError(f"backup file is not a valid database: {exc}") from exc

    if candidate_version > SCHEMA_VERSION:
        tmp_path.unlink(missing_ok=True)
        raise RestoreError(
            f"backup schema version {candidate_version} is newer than this app supports ({SCHEMA_VERSION})"
        )

    pre_restore_backup = create_backup()

    from pdf_document_intelligence.db import connection as connection_module

    with connection_module._lock:
        if connection_module._conn is not None:
            connection_module._conn.close()
            connection_module._conn = None
    shutil.move(str(tmp_path), str(get_db_path()))
    get_connection()  # reopen + run any pending migrations on the restored DB

    return {"restored": True, "preRestoreBackup": str(pre_restore_backup), "metadata": metadata}
