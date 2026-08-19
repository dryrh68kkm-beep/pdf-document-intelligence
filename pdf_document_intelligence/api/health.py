"""Startup integrity + /api/health (spec §27-28): checks the things that
would otherwise fail silently and confusingly later - DB reachable/right
schema, official master actually loaded (with a count, not just "no
exception"), OCR binary present. Never claims "ok" from the absence of an
error; each check does a real read.
"""
from __future__ import annotations

import shutil

from pdf_document_intelligence.catalog.loader import get_default_catalog
from pdf_document_intelligence.db.repository import Repository


def check_health(repo: Repository) -> dict:
    db_health = repo.health()

    try:
        catalog = get_default_catalog()
        master = {"status": "ok" if len(catalog) > 0 else "empty", "count": len(catalog)}
    except Exception as exc:  # noqa: BLE001 - health check must never 500
        master = {"status": "error", "count": 0, "error": str(exc)}

    ocr_available = shutil.which("tesseract") is not None
    local_master_count = repo.count_local_master()

    overall_ok = db_health["status"] == "ok" and master["status"] == "ok"
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
        "ocr": {"available": ocr_available},
    }
