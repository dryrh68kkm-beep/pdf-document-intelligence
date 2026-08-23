"""FastAPI backend for the desktop web application.

Processing runs on a small thread pool, not the request-handling event
loop: PDF extraction/OCR is CPU-bound Python, so the equivalent of a
browser Web Worker here is a background thread + polling progress state,
keeping the API responsive to list/detail/export requests while a
document is mid-pipeline.

State is SQLite-backed (pdf_document_intelligence/db/) so it survives a
server restart; SHA-256 dedup, corrections, and the local product master
all persist across process lifetimes.
"""
from __future__ import annotations

import io
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from pdf_document_intelligence.api import review as review_api
from pdf_document_intelligence.api.aggregate import build_dashboard_state
from pdf_document_intelligence.api.divisions import build_division_departments, build_division_summary
from pdf_document_intelligence.api.health import check_health
from pdf_document_intelligence.api.serialize import _row_stats, document_detail_json, document_summary_json, product_row_json
from pdf_document_intelligence.api.store import store
from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.db import backup as backup_module
from pdf_document_intelligence.export.excel import export_many_to_excel
from pdf_document_intelligence.pipeline.orchestrator import process_document

app = FastAPI(title="PDF Document Intelligence")
_executor = ThreadPoolExecutor(max_workers=2)
_settings = Settings()

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "app"


def _run_processing(doc_id: str, pdf_bytes: bytes) -> None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = Path(tmp.name)
    try:
        result = process_document(
            tmp_path,
            settings=_settings,
            on_progress=lambda stage, current, total: store.set_progress(doc_id, stage, current, total),
        )
        store.set_complete(doc_id, result)
    except Exception as exc:  # noqa: BLE001 - a single bad PDF must not take the API down
        store.set_error(doc_id, str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)


def _doc_products(doc_id: str) -> list[dict]:
    return store.repo.list_product_rows(document_id=doc_id)


def _reprocess_existing(existing: dict, pdf_bytes: bytes) -> dict:
    """Reprocess an already-active document without creating a duplicate row.

    The active-document SHA-256 unique index remains the final data-integrity
    guard.  A forced duplicate upload means "reprocess this exact document",
    not "create a second active copy that would double-count dashboard/export
    totals".
    """
    doc_id = existing["id"]
    store.mark_reprocessing(doc_id)
    _executor.submit(_run_processing, doc_id, pdf_bytes)
    response = document_summary_json(store.get(doc_id))
    response["reprocessedExisting"] = True
    return response


@app.post("/api/documents")
async def upload_document(file: UploadFile, force: bool = False):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are accepted")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, "Empty file")

    import hashlib

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    existing = store.find_by_hash(sha256)
    if existing:
        if force:
            return _reprocess_existing(existing, pdf_bytes)
        return JSONResponse(
            status_code=409,
            content={"error": "duplicate", "existingDocument": document_summary_json(existing)},
        )

    try:
        doc = store.create(file.filename, pdf_bytes)
    except sqlite3.DatabaseError as exc:
        # Two concurrent uploads of the same file can both pass the
        # find_by_hash check before either commits. Depending on sqlite/Python
        # timing, the unique-index violation may surface as IntegrityError or
        # its DatabaseError base class. Only normalize this known constraint.
        if "UNIQUE constraint failed: documents.sha256" not in str(exc):
            raise
        existing = store.find_by_hash(sha256)
        if existing:
            if force:
                return _reprocess_existing(existing, pdf_bytes)
            return JSONResponse(
                status_code=409,
                content={"error": "duplicate", "existingDocument": document_summary_json(existing)},
            )
        raise
    _executor.submit(_run_processing, doc["id"], pdf_bytes)
    return document_summary_json(doc)


@app.get("/api/documents")
def list_documents():
    docs = store.list()
    result = []
    for d in docs:
        rows = _doc_products(d["id"]) if d["status"] == "complete" else []
        stats = _row_stats(rows) if d["status"] == "complete" else None
        result.append(document_summary_json(d, stats))
    return result


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(404, "not found")
    return document_detail_json(doc, _doc_products(doc_id))


@app.get("/api/analytics/documents/{doc_id}/divisions")
def get_document_divisions(doc_id: str):
    return build_division_summary(store.repo, doc_id)


@app.get("/api/analytics/documents/{doc_id}/divisions/{division_code}/departments")
def get_document_division_departments(doc_id: str, division_code: str):
    return build_division_departments(store.repo, doc_id, division_code)


@app.get("/api/documents/{doc_id}/pdf")
def get_document_pdf(doc_id: str):
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(404, "not found")
    pdf_bytes = store.get_pdf_bytes(doc_id)
    if pdf_bytes is None:
        raise HTTPException(404, "pdf file missing on disk")
    return StreamingResponse(io.BytesIO(pdf_bytes), media_type="application/pdf")


@app.post("/api/documents/{doc_id}/reprocess")
def reprocess_document(doc_id: str):
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(404, "not found")
    pdf_bytes = store.get_pdf_bytes(doc_id)
    if pdf_bytes is None:
        raise HTTPException(404, "pdf file missing on disk")
    store.mark_reprocessing(doc_id)
    _executor.submit(_run_processing, doc_id, pdf_bytes)
    return document_summary_json(store.get(doc_id))


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if not store.remove(doc_id):
        raise HTTPException(404, "not found")
    return {"ok": True}


@app.get("/api/products")
def list_all_products():
    docs = {d["id"]: d for d in store.list()}
    rows = store.repo.list_product_rows()
    return [product_row_json(r, docs[r["document_id"]]["filename"]) for r in rows if r["document_id"] in docs]


@app.get("/api/products/{row_id}")
def get_product(row_id: str):
    row = store.repo.get_product_row(row_id)
    if not row:
        raise HTTPException(404, "not found")
    doc = store.get(row["document_id"])
    return product_row_json(row, doc["filename"] if doc else "")


@app.patch("/api/products/{row_id}")
def patch_product(row_id: str, body: dict = Body(...)):
    field_name = body.get("field")
    if not field_name:
        raise HTTPException(400, "'field' is required")
    result = review_api.apply_correction(
        store.repo, row_id, field_name, body.get("value"), body.get("reason"), body.get("source", "LOCAL_USER"),
    )
    doc = store.get(result["row"]["document_id"])
    return {
        "correctionId": result["correction_id"],
        "row": product_row_json(result["row"], doc["filename"] if doc else ""),
    }


@app.get("/api/products/{row_id}/history")
def product_history(row_id: str):
    if not store.repo.get_product_row(row_id):
        raise HTTPException(404, "not found")
    return [
        {
            "id": c["id"], "field": c["field_name"], "oldValue": c["old_value"],
            "newValue": c["new_value"], "reason": c["reason"], "source": c["source"],
            "undoOfId": c["undo_of_id"], "createdAt": c["created_at"],
        }
        for c in store.repo.list_corrections(row_id)
    ]


@app.post("/api/products/{row_id}/undo")
def undo_product_correction(row_id: str, body: dict = Body(...)):
    correction_id = body.get("correctionId")
    if not correction_id:
        raise HTTPException(400, "'correctionId' is required")
    try:
        return store.repo.undo_correction(correction_id, body.get("source", "LOCAL_USER"))
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/review")
def list_review_items():
    return build_dashboard_state(store.repo)["reviewItems"]


@app.post("/api/review/{row_id}/confirm")
def confirm_review(row_id: str, body: dict = Body(default={})):
    return review_api.confirm_review_row(store.repo, row_id, body.get("source", "LOCAL_USER"))


@app.get("/api/master/local")
def list_local_master(search: str | None = Query(default=None)):
    entries = store.repo.list_local_master(search)
    return {"count": len(entries), "entries": entries}


@app.post("/api/master/local")
def add_local_master(body: dict = Body(...)):
    barcode = body.get("barcode")
    product_name = body.get("productName")
    if not barcode or not product_name:
        raise HTTPException(400, "'barcode' and 'productName' are required")
    result = store.repo.add_local_master(
        barcode=barcode, product_name=product_name, department=body.get("department"),
        unit=body.get("unit"), article_code=body.get("articleCode"),
        source_document_id=body.get("sourceDocumentId"),
    )
    return result


@app.get("/api/master/official/count")
def official_master_count():
    from pdf_document_intelligence.catalog.loader import get_default_catalog

    return {"count": len(get_default_catalog())}


_MAX_MASTER_IMPORT_BYTES = 50 * 1024 * 1024  # 50MB


def _snapshot_status_payload() -> dict:
    from datetime import datetime, timezone

    from pdf_document_intelligence.catalog import snapshot as snapshot_module

    path = snapshot_module.get_snapshot_path()
    exists = path.is_file()
    last_updated = None
    product_count = 0
    if exists:
        last_updated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
        try:
            product_count = len(snapshot_module.load_catalog_snapshot().get("products", []))
        except Exception:  # noqa: BLE001 - a corrupt snapshot must not break status reporting
            product_count = 0
    return {
        "exists": exists,
        "productCount": product_count,
        "lastUpdated": last_updated,
        "sourceConfigured": snapshot_module.configured_source_path() is not None,
    }


@app.get("/api/master/snapshot/status")
def master_snapshot_status():
    return _snapshot_status_payload()


@app.post("/api/master/import")
async def import_master_catalog(file: UploadFile):
    from pdf_document_intelligence.catalog import snapshot as snapshot_module

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are accepted")
    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(400, "Empty file")
    if len(csv_bytes) > _MAX_MASTER_IMPORT_BYTES:
        raise HTTPException(400, "File too large (limit 50MB)")

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(csv_bytes)
            tmp_path = Path(tmp.name)
        try:
            snapshot_module.import_catalog_snapshot(tmp_path, overwrite=True)
        except FileNotFoundError as exc:
            raise HTTPException(400, "Could not read uploaded file") from exc
        except (OSError, ValueError, UnicodeError) as exc:
            raise HTTPException(400, f"Failed to import catalog: {exc}") from exc
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    _clear_catalog_caches()
    return _snapshot_status_payload()


def _clear_catalog_caches() -> None:
    """The catalog and department-hierarchy readers are lru_cache'd for the
    life of the process (they're read on every extraction and would
    otherwise mean re-parsing the multi-thousand-row snapshot per row) - a
    runtime import must invalidate all of them or the running process keeps
    matching against the catalog it had in memory before the upload."""
    from pdf_document_intelligence.catalog.loader import get_default_catalog
    from pdf_document_intelligence.templates.department_groups import (
        get_default_department_divisions,
        get_default_department_to_division_code,
        get_default_divisions,
    )

    get_default_catalog.cache_clear()
    get_default_department_divisions.cache_clear()
    get_default_divisions.cache_clear()
    get_default_department_to_division_code.cache_clear()


@app.get("/api/state")
def get_dashboard_state():
    return build_dashboard_state(store.repo)


@app.get("/api/health")
def health():
    return check_health(store.repo)


@app.post("/api/backup")
def create_backup():
    path = backup_module.create_backup()
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/restore")
async def restore_backup(file: UploadFile):
    data = await file.read()
    try:
        return backup_module.restore_backup(data)
    except backup_module.RestoreError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/export.xlsx")
def export_excel():
    doc_ids = [d["id"] for d in store.list() if d["status"] == "complete"]
    if not doc_ids:
        raise HTTPException(400, "No completed documents to export")
    results = [document_detail_json(store.get(did), _doc_products(did)) for did in doc_ids]
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        out_path = Path(tmp.name)
    export_many_to_excel(results, out_path)
    return FileResponse(
        out_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="pdf-document-intelligence-export.xlsx",
        background=BackgroundTask(out_path.unlink, missing_ok=True),
    )


class _NoCacheStaticFiles(StaticFiles):
    """The frontend has no build step or filename hashing, so a browser that
    caches index.html/main.js/styles.css keeps rendering a stale UI after an
    update - confirmed in practice (a user reinstalling a new UI redesign
    kept seeing the old one until a hard refresh). Forcing revalidation on
    every request costs nothing on an offline desktop app served from
    localhost and guarantees an update is visible on the next normal reload."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return response


if FRONTEND_DIR.exists():
    app.mount("/", _NoCacheStaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
