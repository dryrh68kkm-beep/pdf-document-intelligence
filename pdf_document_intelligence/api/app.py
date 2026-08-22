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

from pdf_document_intelligence.api.aggregate import router as aggregate_router
from pdf_document_intelligence.api.divisions import router as divisions_router
from pdf_document_intelligence.api.health import router as health_router
from pdf_document_intelligence.api.review import router as review_router
from pdf_document_intelligence.api.rows import prepare_flat_rows
from pdf_document_intelligence.api.serialize import document_detail_json, document_summary_json
from pdf_document_intelligence.api.store import store
from pdf_document_intelligence.catalog.apply import apply_catalog
from pdf_document_intelligence.config.settings import settings
from pdf_document_intelligence.export.excel import export_document_excel
from pdf_document_intelligence.pipeline.orchestrator import process_document

app = FastAPI(title="PDF Document Intelligence")
app.include_router(health_router)
app.include_router(aggregate_router)
app.include_router(divisions_router)
app.include_router(review_router)
_executor = ThreadPoolExecutor(max_workers=2)


def _doc_products(doc_id: str) -> list[dict]:
    return store.repo.list_product_rows(document_id=doc_id)


def _run_processing(doc_id: str, pdf_bytes: bytes) -> None:
    def progress(stage: str, current: int, total: int) -> None:
        store.set_progress(doc_id, stage, current, total)

    try:
        result = process_document(pdf_bytes, progress_callback=progress)
        apply_catalog(result)
        store.set_complete(doc_id, result)
    except Exception as exc:  # background worker boundary: persist the error
        store.set_error(doc_id, str(exc))


def _reprocess_existing(existing: dict, pdf_bytes: bytes) -> dict:
    """Force-processing reuses the existing document identity.

    SHA-256 is globally unique among active documents, so force means
    "reprocess the existing record with fresh extraction results", not
    "create a second active copy that would double-count dashboard/export
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
        # Two concurrent uploads can both pass find_by_hash before either
        # insert commits. Depending on sqlite/Python timing, the unique-index
        # violation may surface as IntegrityError or its DatabaseError base.
        # Convert only this known constraint race to the normal duplicate 409;
        # all unrelated database failures must still propagate.
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
        result.append(document_summary_json(d, rows))
    return result


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    doc = store.get(doc_id)
    if not doc or doc.get("deletedAt") or doc.get("deleted_at"):
        raise HTTPException(404, "Document not found")
    return document_detail_json(doc, _doc_products(doc_id))


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if not store.remove(doc_id):
        raise HTTPException(404, "Document not found")
    return {"ok": True}


@app.post("/api/documents/{doc_id}/reprocess")
def reprocess_document(doc_id: str):
    doc = store.get(doc_id)
    if not doc or doc.get("deleted_at"):
        raise HTTPException(404, "Document not found")
    pdf_bytes = store.get_pdf_bytes(doc_id)
    if pdf_bytes is None:
        raise HTTPException(409, "Original PDF is not available")
    return _reprocess_existing(doc, pdf_bytes)


@app.get("/api/documents/{doc_id}/export")
def export_document(doc_id: str):
    doc = store.get(doc_id)
    if not doc or doc.get("deleted_at"):
        raise HTTPException(404, "Document not found")
    rows = _doc_products(doc_id)
    output = io.BytesIO()
    export_document_excel(doc, rows, output)
    output.seek(0)
    filename = f"{Path(doc['filename']).stem}_review.xlsx"
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/documents/{doc_id}/pdf")
def get_pdf(doc_id: str):
    doc = store.get(doc_id)
    if not doc or doc.get("deleted_at"):
        raise HTTPException(404, "Document not found")
    pdf_bytes = store.get_pdf_bytes(doc_id)
    if pdf_bytes is None:
        raise HTTPException(404, "PDF not found")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(pdf_bytes)
    tmp.close()
    return FileResponse(
        tmp.name,
        media_type="application/pdf",
        filename=doc["filename"],
        background=BackgroundTask(Path(tmp.name).unlink, missing_ok=True),
    )


@app.patch("/api/products/{row_id}")
def patch_product(row_id: str, payload: dict = Body(...)):
    field = payload.get("field")
    if not isinstance(field, str) or not field:
        raise HTTPException(400, "field is required")
    if "value" not in payload:
        raise HTTPException(400, "value is required")
    try:
        return store.repo.correct_product_field(
            row_id,
            field,
            payload["value"],
            reason=str(payload.get("reason") or "manual review"),
            corrected_by=str(payload.get("correctedBy") or "user"),
        )
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/products")
def list_products(
    documentId: str | None = Query(None),
    department: str | None = Query(None),
    q: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    return store.repo.list_product_rows(
        document_id=documentId,
        department=department,
        q=q,
        limit=limit,
        offset=offset,
    )


@app.get("/api/settings")
def get_settings():
    return {
        "dataDir": str(settings.data_dir),
        "ocrEnabled": settings.ocr_enabled,
    }


# Static frontend is mounted last so /api routes take precedence.
_FRONTEND = Path(__file__).parent.parent.parent / "frontend" / "app"
if _FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="frontend")
