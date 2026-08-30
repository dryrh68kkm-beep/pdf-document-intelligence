"""Startup integrity + /api/health (spec §27-28): checks the things that
would otherwise fail silently and confusingly later - DB reachable/right
schema, official master actually loaded (with a count, not just "no
exception"), OCR binary present. Never claims "ok" from the absence of an
error; each check does a real read.

Hardening pass (production-readiness): every check below is additive to
the original response shape - no existing field's name or meaning changes,
so any caller already reading `database.status`, `productMaster.*`, or
`ocr.available` keeps working unchanged. New checks are exposed both as
their own top-level sections (dataDirectory, tempDirectory, diskSpace,
ocr.thaiLanguagePack) and rolled into a flat `checks` list, each entry
categorized ok/warning/error, so a monitoring script can iterate one list
instead of knowing every section's shape.

Never leaks: absolute filesystem paths, environment secrets (the admin
passphrase), or raw exception text - only short, generic status strings
and counts. A check that fails to run is reported as "error" with a
generic reason, never with str(exc) (which could contain a path or other
internal detail).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from pdf_document_intelligence.catalog.loader import get_default_catalog
from pdf_document_intelligence.db.paths import get_data_dir
from pdf_document_intelligence.db.repository import Repository

# Below this much free space on the data volume, treat it as a hard error
# (imminent write failures) rather than a warning.
_DISK_SPACE_ERROR_BYTES = 200 * 1024 * 1024  # 200MB
# Below this, warn (still writable, but an operator should look soon).
_DISK_SPACE_WARNING_BYTES = 2 * 1024 * 1024 * 1024  # 2GB


def _check_directory_writable(path) -> bool:
    """Real write-then-clean-up probe, not just os.access - os.access can
    report a false positive/negative on some Windows ACL configurations,
    and a health check must never just claim writability from the absence
    of an obvious error."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".health_check_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _check_thai_language_pack() -> dict:
    """Tesseract can be installed with only its default (English) language
    data - this app requires the Thai pack ("tha") specifically, and a
    missing pack fails silently mid-OCR with a cryptic pytesseract error
    rather than at startup, so it gets its own explicit check."""
    if shutil.which("tesseract") is None:
        return {"available": False, "status": "error"}
    try:
        import pytesseract

        langs = set(pytesseract.get_languages(config=""))
        available = "tha" in langs
        return {"available": available, "status": "ok" if available else "error"}
    except Exception:  # noqa: BLE001 - health check must never 500
        return {"available": False, "status": "error"}


def _check_disk_space(data_dir) -> dict:
    try:
        usage = shutil.disk_usage(data_dir)
    except Exception:  # noqa: BLE001 - health check must never 500, never leak exception text
        return {"status": "error", "freeMb": None}
    free_mb = usage.free // (1024 * 1024)
    if usage.free < _DISK_SPACE_ERROR_BYTES:
        status = "error"
    elif usage.free < _DISK_SPACE_WARNING_BYTES:
        status = "warning"
    else:
        status = "ok"
    return {"status": status, "freeMb": int(free_mb)}


def check_health(repo: Repository) -> dict:
    db_health = repo.health()

    try:
        catalog = get_default_catalog()
        master = {"status": "ok" if len(catalog) > 0 else "empty", "count": len(catalog)}
    except Exception:  # noqa: BLE001 - health check must never 500, never leak exception text
        master = {"status": "error", "count": 0}

    ocr_available = shutil.which("tesseract") is not None
    local_master_count = repo.count_local_master()
    thai_pack = _check_thai_language_pack()

    try:
        data_dir = get_data_dir()
        data_dir_writable = _check_directory_writable(data_dir)
    except OSError:
        data_dir = None
        data_dir_writable = False

    try:
        temp_dir_writable = _check_directory_writable(Path(tempfile.gettempdir()) / "pdf_document_intelligence_healthcheck")
    except OSError:
        temp_dir_writable = False

    disk_space = _check_disk_space(data_dir) if data_dir is not None else {"status": "error", "freeMb": None}

    # `database.status`/`productMaster.status`/`ocr.available` are the
    # pre-existing fields this endpoint has always returned - their
    # meaning is unchanged; overall `status` additionally degrades on any
    # new "error"-level check (a missing Thai pack, an unwritable data or
    # temp dir) but not on a "warning"-level one (e.g. low disk space
    # still has room to operate).
    new_error_checks = (
        thai_pack["status"] == "error"
        or not data_dir_writable
        or not temp_dir_writable
        or disk_space["status"] == "error"
    )
    overall_ok = db_health["status"] == "ok" and master["status"] == "ok" and not new_error_checks

    # productMaster.status has its own pre-existing "empty" value (catalog
    # loaded fine but has zero rows) alongside "ok"/"error" - unchanged
    # here. The flat `checks` list promises every entry uses only
    # ok/warning/error, so "empty" (still operable, just worth a look) is
    # mapped to "warning" for that list only; productMaster.status itself
    # is untouched above.
    product_master_check_status = {"ok": "ok", "empty": "warning", "error": "error"}.get(
        master["status"], "warning"
    )
    checks = [
        {"name": "database", "status": db_health["status"] if db_health["status"] in ("ok", "warning", "error") else "error"},
        {"name": "productMaster", "status": product_master_check_status},
        {"name": "ocrBinary", "status": "ok" if ocr_available else "error"},
        {"name": "ocrThaiLanguagePack", "status": thai_pack["status"]},
        {"name": "dataDirectoryWritable", "status": "ok" if data_dir_writable else "error"},
        {"name": "tempDirectoryWritable", "status": "ok" if temp_dir_writable else "error"},
        {"name": "diskSpace", "status": disk_space["status"]},
    ]

    return {
        "status": "ok" if overall_ok else "degraded",
        "database": {
            "status": db_health["status"],
            "schemaVersion": db_health["schemaVersion"],
            "expectedSchemaVersion": db_health["expectedSchemaVersion"],
        },
        "productMaster": {
            "status": master["status"],
            "officialCount": master["count"],
            "localCount": local_master_count,
        },
        "ocr": {
            "available": ocr_available,
            "thaiLanguagePack": thai_pack,
        },
        "dataDirectory": {"writable": data_dir_writable},
        "tempDirectory": {"writable": temp_dir_writable},
        "diskSpace": disk_space,
        "checks": checks,
    }
