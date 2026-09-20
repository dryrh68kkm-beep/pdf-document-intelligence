"""Full backup/restore: DB + source PDFs + master catalog snapshot in one
archive (spec P6 §24-26, extended per PR2 - a DB-only backup silently lost
every source PDF and the compiled master catalog on restore).

A backup is a zip containing:
  - app.db          a consistent snapshot of the DB (via SQLite's own
                     backup API, safe even while the server is running)
  - pdfs/<id>.pdf    every source PDF currently on disk
  - master_catalog.snapshot.json   the compiled master catalog, if one
                     has been imported
  - metadata.json    backup format version, app version, DB schema
                     version, counts, and a sha256 checksum for every
                     other member - restore refuses to trust a member
                     whose checksum doesn't match before touching disk

Restore validates the whole archive (member names against the fixed set
above - no path traversal is possible since nothing else is ever
extracted; checksums; DB schema version) before mutating anything, backs
up the *current* installation first (so a bad restore is itself
undoable), then applies the PDFs and master snapshot before the DB swap
so a failure partway through leaves the *original* DB - and therefore
the original document list - intact rather than a document set that no
longer matches what's on disk.

A backup made before this format existed (or with a corrupted/missing
metadata.json) is treated as a legacy, DB-only backup: still restorable,
but the result is reported with `"legacy": True` and 0 PDFs/no master
snapshot restored rather than silently claiming a full restore.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from pdf_document_intelligence.catalog.snapshot import SNAPSHOT_FILENAME
from pdf_document_intelligence.db.connection import get_connection, get_write_lock
from pdf_document_intelligence.db.migrations import SCHEMA_VERSION, current_version
from pdf_document_intelligence.db.paths import get_data_dir, get_db_path

BACKUP_FORMAT_VERSION = 2
_PDF_MEMBER_PREFIX = "pdfs/"
# new_id() (db/repository.py) is str(uuid.uuid4()) - 36 hex/hyphen chars.
_SAFE_PDF_NAME_RE = re.compile(r"^[0-9a-fA-F-]{1,64}\.pdf$")


def _app_version() -> str:
    try:
        return importlib.metadata.version("pdf-document-intelligence")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _unique_suffix() -> str:
    """Keep human-readable timestamps while avoiding same-second collisions."""
    return uuid.uuid4().hex[:8]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def create_backup() -> Path:
    conn = get_connection()
    version = current_version(conn)

    data_dir = get_data_dir()
    backups_dir = data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    stamp = _timestamp()
    suffix = _unique_suffix()
    snapshot_path = backups_dir / f"_snapshot-{stamp}-{suffix}.db"
    zip_path = backups_dir / f"backup-{stamp}-{suffix}.zip"
    # Written under a temp name and only renamed to the real backup path on
    # success, so a failure partway through zip-writing (disk full, a PDF
    # deleted mid-backup, ...) never leaves a half-written file sitting at
    # the path a later restore/listing would otherwise treat as a real one.
    tmp_zip_path = backups_dir / f"_backup-{stamp}-{suffix}.zip.tmp"

    dest_conn = None
    try:
        dest_conn = sqlite3.connect(str(snapshot_path))
        with dest_conn:
            conn.backup(dest_conn)
        dest_conn.close()
        dest_conn = None

        counts = {
            "documents": conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "productRows": conn.execute("SELECT COUNT(*) FROM product_rows").fetchone()[0],
            "localMaster": conn.execute("SELECT COUNT(*) FROM local_product_master").fetchone()[0],
        }

        pdfs_dir = data_dir / "pdfs"
        pdf_paths = sorted(pdfs_dir.glob("*.pdf")) if pdfs_dir.is_dir() else []
        snapshot_json_path = data_dir / SNAPSHOT_FILENAME
        has_master_snapshot = snapshot_json_path.is_file()

        checksums: dict[str, str] = {"app.db": _sha256_file(snapshot_path)}

        with zipfile.ZipFile(tmp_zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot_path, "app.db")
            for pdf_path in pdf_paths:
                member = f"{_PDF_MEMBER_PREFIX}{pdf_path.name}"
                checksums[member] = _sha256_file(pdf_path)
                zf.write(pdf_path, member)
            if has_master_snapshot:
                checksums[SNAPSHOT_FILENAME] = _sha256_file(snapshot_json_path)
                zf.write(snapshot_json_path, SNAPSHOT_FILENAME)

            metadata = {
                "backupFormatVersion": BACKUP_FORMAT_VERSION,
                "appVersion": _app_version(),
                "schemaVersion": version,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "counts": counts,
                "pdfCount": len(pdf_paths),
                "hasMasterSnapshot": has_master_snapshot,
                "checksums": checksums,
            }
            zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False, indent=2))

        tmp_zip_path.replace(zip_path)
        return zip_path
    finally:
        if dest_conn is not None:
            dest_conn.close()
        snapshot_path.unlink(missing_ok=True)
        tmp_zip_path.unlink(missing_ok=True)


class RestoreError(Exception):
    pass


class RestoreConflictError(RestoreError):
    """A document is still processing - restore refused. A distinct type
    (not just a message an API layer would have to pattern-match) so
    api/app.py can map this specifically to 423 Locked, matching the
    delete-while-processing convention (see delete_document), rather than
    RestoreError's default 400. Still a RestoreError, so existing callers
    that only catch the base class keep working."""

    pass


def _validate_member_name(name: str) -> None:
    """Every member a restore archive is allowed to contain - anything
    else (a '..' path-traversal attempt, an absolute path, an unexpected
    directory) is rejected outright, before a single byte is read from
    it, let alone written to disk."""
    if name in ("app.db", "metadata.json", SNAPSHOT_FILENAME):
        return
    if name.startswith(_PDF_MEMBER_PREFIX):
        pdf_name = name[len(_PDF_MEMBER_PREFIX) :]
        if "/" not in pdf_name and _SAFE_PDF_NAME_RE.match(pdf_name):
            return
    raise RestoreError(f"backup archive contains an unexpected entry: {name!r}")


def _atomic_replace(source: Path, target: Path) -> None:
    """Same-filesystem rename/replace seam used by restore.

    Keeping this tiny wrapper makes the multi-file restore transaction
    testable: tests can fail one swap deliberately and prove every already-
    moved live asset is rolled back."""
    source.replace(target)


def restore_backup(zip_bytes: bytes) -> dict:
    import io

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        for name in names:
            _validate_member_name(name)
        if "app.db" not in names:
            raise RestoreError("backup zip missing app.db")

        try:
            metadata = json.loads(zf.read("metadata.json")) if "metadata.json" in names else {}
        except json.JSONDecodeError as exc:
            raise RestoreError(f"backup metadata.json is corrupt: {exc}") from exc
        if not isinstance(metadata, dict):
            metadata = {}
        checksums = metadata.get("checksums") if isinstance(metadata.get("checksums"), dict) else {}
        is_legacy = metadata.get("backupFormatVersion") != BACKUP_FORMAT_VERSION or not checksums

        db_bytes = zf.read("app.db")
        expected = checksums.get("app.db")
        if expected and _sha256_bytes(db_bytes) != expected:
            raise RestoreError("app.db checksum mismatch - backup file is corrupt")

        pdf_payloads: dict[str, bytes] = {}
        for member in names:
            if not member.startswith(_PDF_MEMBER_PREFIX):
                continue
            data = zf.read(member)
            expected = checksums.get(member)
            if expected and _sha256_bytes(data) != expected:
                raise RestoreError(f"{member} checksum mismatch - backup file is corrupt")
            pdf_payloads[member] = data

        master_snapshot_bytes: bytes | None = None
        if SNAPSHOT_FILENAME in names:
            master_snapshot_bytes = zf.read(SNAPSHOT_FILENAME)
            expected = checksums.get(SNAPSHOT_FILENAME)
            if expected and _sha256_bytes(master_snapshot_bytes) != expected:
                raise RestoreError(f"{SNAPSHOT_FILENAME} checksum mismatch - backup file is corrupt")
            try:
                json.loads(master_snapshot_bytes)
            except json.JSONDecodeError as exc:
                raise RestoreError(f"{SNAPSHOT_FILENAME} is corrupt: {exc}") from exc

        if not is_legacy:
            declared_pdf_count = metadata.get("pdfCount")
            if declared_pdf_count != len(pdf_payloads):
                raise RestoreError(
                    f"backup metadata pdfCount={declared_pdf_count!r} does not match archive ({len(pdf_payloads)})"
                )
            declared_master = bool(metadata.get("hasMasterSnapshot"))
            if declared_master != (master_snapshot_bytes is not None):
                raise RestoreError("backup metadata master-snapshot flag does not match archive contents")

    data_dir = get_data_dir()
    token = f"{_timestamp()}-{_unique_suffix()}"
    tmp_path = data_dir / f"_restore-candidate-{token}.db"
    stage_root = data_dir / f"_restore-stage-{token}"
    stage_pdfs = stage_root / "pdfs"
    stage_snapshot = stage_root / SNAPSHOT_FILENAME

    tmp_path.write_bytes(db_bytes)
    try:
        try:
            candidate_conn = sqlite3.connect(str(tmp_path))
            candidate_version = current_version(candidate_conn)
            candidate_conn.close()
        except sqlite3.Error as exc:
            raise RestoreError(f"backup file is not a valid database: {exc}") from exc

        if candidate_version > SCHEMA_VERSION:
            raise RestoreError(
                f"backup schema version {candidate_version} is newer than this app supports ({SCHEMA_VERSION})"
            )

        # Stage every non-DB asset completely before touching the live
        # installation. Full-format backups are exact snapshots: an empty
        # pdfs/ set must remove old/orphan PDFs, and a backup with no master
        # snapshot must remove a newer live snapshot. Legacy DB-only backups
        # intentionally leave those assets alone.
        if not is_legacy:
            stage_pdfs.mkdir(parents=True, exist_ok=False)
            for member, data in pdf_payloads.items():
                pdf_name = member[len(_PDF_MEMBER_PREFIX) :]
                (stage_pdfs / pdf_name).write_bytes(data)
            if master_snapshot_bytes is not None:
                stage_snapshot.write_bytes(master_snapshot_bytes)

        with get_write_lock():
            processing = get_connection().execute(
                "SELECT COUNT(*) FROM documents WHERE status='processing'"
            ).fetchone()[0]
            if processing:
                raise RestoreConflictError(
                    f"cannot restore while {processing} document(s) are still processing"
                )

            pre_restore_backup = create_backup()

            pdfs_dir = data_dir / "pdfs"
            snapshot_target = data_dir / SNAPSHOT_FILENAME
            db_path = get_db_path()
            old_pdfs = data_dir / f"_restore-old-pdfs-{token}"
            old_snapshot = data_dir / f"_restore-old-master-{token}.json"
            old_db = data_dir / f"_restore-old-app-{token}.db"

            pdf_original_moved = False
            pdf_stage_installed = False
            snapshot_original_moved = False
            snapshot_stage_installed = False
            db_original_moved = False
            db_stage_installed = False

            def rollback_assets() -> None:
                nonlocal pdf_stage_installed, snapshot_stage_installed
                if not is_legacy:
                    if pdf_stage_installed and pdfs_dir.exists():
                        shutil.rmtree(pdfs_dir, ignore_errors=True)
                        pdf_stage_installed = False
                    if pdf_original_moved and old_pdfs.exists():
                        _atomic_replace(old_pdfs, pdfs_dir)

                    if snapshot_stage_installed:
                        snapshot_target.unlink(missing_ok=True)
                        snapshot_stage_installed = False
                    if snapshot_original_moved and old_snapshot.exists():
                        _atomic_replace(old_snapshot, snapshot_target)

            try:
                if not is_legacy:
                    if pdfs_dir.exists():
                        _atomic_replace(pdfs_dir, old_pdfs)
                        pdf_original_moved = True
                    _atomic_replace(stage_pdfs, pdfs_dir)
                    pdf_stage_installed = True

                    if snapshot_target.exists():
                        _atomic_replace(snapshot_target, old_snapshot)
                        snapshot_original_moved = True
                    if stage_snapshot.exists():
                        _atomic_replace(stage_snapshot, snapshot_target)
                        snapshot_stage_installed = True

                from pdf_document_intelligence.db import connection as connection_module

                # Close the one live SQLite handle before swapping database
                # files. Keep the old DB beside it until the restored DB has
                # reopened successfully, so a failed candidate activation can
                # be rolled back without relying on the ZIP backup.
                with connection_module._lock:
                    if connection_module._conn is not None:
                        connection_module._conn.close()
                        connection_module._conn = None

                for suffix in ("-wal", "-shm"):
                    Path(str(db_path) + suffix).unlink(missing_ok=True)

                if db_path.exists():
                    _atomic_replace(db_path, old_db)
                    db_original_moved = True
                try:
                    _atomic_replace(tmp_path, db_path)
                    db_stage_installed = True
                    restored_conn = get_connection()  # reopen + run pending migrations
                except Exception:
                    with connection_module._lock:
                        if connection_module._conn is not None:
                            connection_module._conn.close()
                            connection_module._conn = None
                    if db_stage_installed:
                        db_path.unlink(missing_ok=True)
                        db_stage_installed = False
                    if db_original_moved and old_db.exists():
                        _atomic_replace(old_db, db_path)
                    get_connection()
                    rollback_assets()
                    raise

                missing_pdfs = []
                for row in restored_conn.execute("SELECT id FROM documents WHERE deleted_at IS NULL"):
                    if not (data_dir / "pdfs" / f"{row['id']}.pdf").is_file():
                        missing_pdfs.append(row["id"])

                # Commit point: DB reopened successfully and the matching
                # staged assets are live. Old copies are now safe to delete.
                if old_pdfs.exists():
                    shutil.rmtree(old_pdfs, ignore_errors=True)
                old_snapshot.unlink(missing_ok=True)
                old_db.unlink(missing_ok=True)

                return {
                    "restored": True,
                    "legacy": is_legacy,
                    "preRestoreBackup": str(pre_restore_backup),
                    "metadata": metadata,
                    "pdfsRestored": len(pdf_payloads),
                    "masterSnapshotRestored": master_snapshot_bytes is not None,
                    "missingPdfCount": len(missing_pdfs),
                }
            except Exception:
                # Failures before/during the DB swap must leave all live
                # assets exactly as they were. The DB-specific except above
                # performs DB rollback; this covers a PDF/master swap failure.
                if not db_stage_installed:
                    rollback_assets()
                raise
    finally:
        tmp_path.unlink(missing_ok=True)
        if stage_root.exists():
            shutil.rmtree(stage_root, ignore_errors=True)
