"""FastAPI backend for the desktop web application.

Processing runs on a small thread pool, not the request-handling event
loop: PDF extraction/OCR is CPU-bound Python, so the equivalent of a
browser Web Worker here is a background thread + polling progress state,
keeping the API responsive to list/detail/export requests while a
document is mid-pipeline (spec §23-24, adapted to a server-side
extraction engine rather than an in-browser one).
"""
from __future__ import annotations

import io
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pdf_document_intelligence.api.aggregate import build_dashboard_state
from pdf_document_intelligence.api.serialize import all_products_json, document_detail_json, document_summary_json
from pdf_document_intelligence.api.store import DocumentEntry, store
from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.export.excel import export_many_to_excel
from pdf_document_intelligence.pipeline.orchestrator import process_document

app = FastAPI(title="PDF Document Intelligence")
_executor = ThreadPoolExecutor(max_workers=2)
_settings = Settings()

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "app"


def _run_processing(entry: DocumentEntry) -> None:
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(entry.pdf_bytes)
        tmp_path = Path(tmp.name)
    try:
        result = process_document(
            tmp_path,
            settings=_settings,
            on_progress=lambda stage, current, total: store.set_progress(entry.id, stage, current, total),
        )
        store.set_complete(entry.id, result)
    except Exception as exc:  # noqa: BLE001 - a single bad PDF must not take the API down
        store.set_error(entry.id, str(exc))
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/api/documents")
async def upload_document(file: UploadFile, force: bool = False):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are accepted")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(400, "Empty file")

    import hashlib

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    if not force:
        existing = store.find_by_hash(sha256)
        if existing:
            return JSONResponse(
                status_code=409,
                content={"error": "duplicate", "existingDocument": document_summary_json(existing)},
            )

    entry = store.create(file.filename, pdf_bytes)
    _executor.submit(_run_processing, entry)
    return document_summary_json(entry)


@app.get("/api/documents")
def list_documents():
    return [document_summary_json(d) for d in store.list()]


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str):
    entry = store.get(doc_id)
    if not entry:
        raise HTTPException(404, "not found")
    return document_detail_json(entry)


@app.get("/api/documents/{doc_id}/pdf")
def get_document_pdf(doc_id: str):
    entry = store.get(doc_id)
    if not entry:
        raise HTTPException(404, "not found")
    return StreamingResponse(io.BytesIO(entry.pdf_bytes), media_type="application/pdf")


@app.post("/api/documents/{doc_id}/reprocess")
def reprocess_document(doc_id: str):
    entry = store.get(doc_id)
    if not entry:
        raise HTTPException(404, "not found")
    entry.status = "processing"
    entry.result = None
    entry.error = None
    _executor.submit(_run_processing, entry)
    return document_summary_json(entry)


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    if not store.remove(doc_id):
        raise HTTPException(404, "not found")
    return {"ok": True}


@app.get("/api/products")
def list_all_products():
    return all_products_json(store.list())


@app.get("/api/state")
def get_dashboard_state():
    return build_dashboard_state(store.list())


@app.get("/api/export.xlsx")
def export_excel():
    completed = [d.result for d in store.list() if d.status == "complete" and d.result]
    if not completed:
        raise HTTPException(400, "No completed documents to export")
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        out_path = Path(tmp.name)
    export_many_to_excel(completed, out_path)
    return FileResponse(
        out_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="pdf-document-intelligence-export.xlsx",
    )


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
