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

import hashlib
import hmac
import logging
import os
import secrets
import shutil
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
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
from pdf_document_intelligence.db.paths import get_data_dir, get_pdf_path
from pdf_document_intelligence.db.repository import new_id
from pdf_document_intelligence.export.excel import export_many_to_excel
from pdf_document_intelligence.loader.preflight import PreflightError
from pdf_document_intelligence.pipeline.orchestrator import process_document

_logger = logging.getLogger("pdf_document_intelligence")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # See DocumentStore.recover_interrupted_processing()'s own docstring for
    # the full story - a document left status='processing' by a killed
    # previous server process is otherwise a permanent dead end (can't be
    # reprocessed or removed through the UI). This process has not submitted
    # any processing job yet at startup, so anything still 'processing' here
    # is unconditionally leftover from before the restart.
    recovered = store.recover_interrupted_processing()
    if recovered:
        _logger.warning(
            "Recovered %d document(s) stuck in 'processing' from before this server started: %s",
            len(recovered), recovered,
        )
    yield


app = FastAPI(title="PDF Document Intelligence", lifespan=_lifespan)
_executor = ThreadPoolExecutor(max_workers=2)
_settings = Settings()
# Not a hard concurrency limit (max_workers already caps that) - a backlog
# cap. ThreadPoolExecutor's own work queue is unbounded by default, so
# without this a burst of uploads would just pile up invisibly instead of
# giving the user a clear "try again later" instead of a silently growing
# wait.
_MAX_QUEUED_PROCESSING_JOBS = 10
_UPLOAD_CHUNK_SIZE = 1024 * 1024

FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend" / "app"


def _require_admin(x_admin_passphrase: str | None = Header(None)) -> None:
    """Viewer/Admin gate (PR13) - not a login system, a single shared
    passphrase an operator can turn on for a LAN deployment where not
    everyone with network access should be able to upload, delete,
    correct data, or restore a backup. `_settings.admin_passphrase` empty
    (the default) means this is a no-op for every caller, so a deployment
    that never configured it behaves exactly as before this PR. When it
    is set, every mutating endpoint requires the same passphrase echoed
    back in the X-Admin-Passphrase header - compared with hmac.compare_digest
    to avoid a timing side-channel on the comparison."""
    if not _settings.admin_passphrase:
        return
    if not x_admin_passphrase or not hmac.compare_digest(x_admin_passphrase, _settings.admin_passphrase):
        raise HTTPException(403, "Admin access required")


@app.get("/api/auth/admin-status")
def admin_status():
    return {"adminRequired": bool(_settings.admin_passphrase)}


@app.post("/api/auth/admin-unlock")
def admin_unlock(body: dict = Body(...)):
    # Lets the frontend validate a passphrase once (to show a clear "wrong
    # passphrase" message immediately) before storing it in sessionStorage
    # for reuse on every subsequent mutating request - not a session token,
    # so there is nothing server-side to expire or invalidate.
    if not _settings.admin_passphrase:
        return {"ok": True}
    passphrase = body.get("passphrase") or ""
    if not hmac.compare_digest(passphrase, _settings.admin_passphrase):
        raise HTTPException(403, "Incorrect passphrase")
    return {"ok": True}


def _new_diagnostic_id() -> str:
    """Short, greppable-in-logs identifier for a single unhandled-exception
    occurrence - lets a user hand the operator "ERR-A1B2C3D4" instead of a
    vague "it just says 500" report, and lets the operator jump straight to
    the matching traceback in the server log instead of hunting by
    timestamp."""
    return f"ERR-{secrets.token_hex(4).upper()}"


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Starlette's own default for an uncaught exception is a bare
    # PlainTextResponse("Internal Server Error") with no detail - the
    # frontend's error dialogs (api.js's json() helper) show that verbatim,
    # so a real failure here reads as an opaque "500 Internal Server
    # Error" with nothing to diagnose from (reported live: reprocessing a
    # document failed with exactly that message and no further clue).
    # The previous fix (returning str(exc) to the client) made the *next*
    # failure diagnosable but also handed the browser whatever the raw
    # exception message happened to contain - which can include file
    # paths, SQL fragments, or other internals never meant to leave the
    # server. Logging the full traceback server-side (still keyed by
    # method/path) and returning only a generic message plus a diagnostic
    # ID keeps the client-visible response safe while keeping the server
    # log just as actionable as before.
    diagnostic_id = _new_diagnostic_id()
    _logger.exception("Unhandled exception [%s] on %s %s", diagnostic_id, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "diagnosticId": diagnostic_id,
            "message": "An unexpected error occurred. Please try again or contact support with this diagnostic ID.",
            "type": type(exc).__name__,
        },
    )


def _run_processing(doc_id: str) -> None:
    # The upload/reprocess path always has the PDF safely on disk at its
    # permanent location (get_pdf_path) before this is ever submitted to
    # the executor - no bytes are handed across the thread boundary and no
    # second temp copy needs writing/cleaning up here anymore, unlike the
    # previous pdf_bytes-in-memory version of this function.
    pdf_path = get_pdf_path(doc_id)
    last_stage = "start"

    def _on_progress(stage: str, current: int, total: int) -> None:
        nonlocal last_stage
        last_stage = stage
        store.set_progress(doc_id, stage, current, total)

    try:
        result = process_document(pdf_path, settings=_settings, on_progress=_on_progress)
        store.set_complete(doc_id, result)
    except PreflightError as exc:
        # A rejection before any page was read (corrupted file,
        # password-protected, wrong signature, too many pages, ...) - the
        # exception's own `code` (e.g. PDF_PASSWORD_REQUIRED) is prefixed
        # onto the stored message so the Documents page's error text tells
        # the user which specific preflight check failed, not just that
        # "something" did.
        diagnostic_id = _new_diagnostic_id()
        _logger.exception(
            "Preflight rejected [%s] document %s: %s", diagnostic_id, doc_id, exc.code
        )
        store.set_error(doc_id, f"{exc.code}: {exc}")
    except Exception as exc:  # noqa: BLE001 - a single bad PDF must not take the API down
        # This runs on a worker thread, outside the request/response cycle,
        # so the global exception_handler above never sees it - logging a
        # diagnostic ID here too keeps a background processing failure just
        # as traceable in the server log as a request-cycle one. The
        # document's own `error` field still gets the plain message (a
        # parse/OCR failure like "not a valid PDF structure" is meaningful,
        # user-facing information about *this file*, not an internal leak).
        diagnostic_id = _new_diagnostic_id()
        _logger.exception(
            "Processing failed [%s] for document %s at stage %s", diagnostic_id, doc_id, last_stage
        )
        store.set_error(doc_id, str(exc))


def _doc_products(doc_id: str) -> list[dict]:
    return store.repo.list_product_rows(document_id=doc_id)


def _reprocess_existing(existing: dict, source_path: Path) -> dict:
    """Reprocess an already-active document without creating a duplicate row.

    The active-document SHA-256 unique index remains the final data-integrity
    guard.  A forced duplicate upload means "reprocess this exact document",
    not "create a second active copy that would double-count dashboard/export
    totals". `source_path` is wherever the newly-uploaded bytes currently sit
    on disk (the streamed temp file, or - on the concurrent-duplicate-race
    path - the file already moved to a fresh doc_id's slot before the DB
    insert lost the race); it's moved into the existing document's own PDF
    path, overwriting the previous version.

    mark_reprocessing() is called - and checked - before anything on disk is
    touched: it atomically claims the document for this run, so if a job is
    already in flight for it (another force-upload of the same file, or the
    dedicated Reprocess button, racing this one) the newly-uploaded file is
    discarded and the document already being processed is left completely
    untouched, rather than overwriting its PDF out from under the running job.
    """
    doc_id = existing["id"]
    if not store.mark_reprocessing(doc_id):
        source_path.unlink(missing_ok=True)
        raise HTTPException(423, "cannot reprocess a document while it is already processing")
    shutil.move(str(source_path), str(get_pdf_path(doc_id)))
    _executor.submit(_run_processing, doc_id)
    response = document_summary_json(store.get(doc_id))
    response["reprocessedExisting"] = True
    return response


def _count_processing_documents() -> int:
    return sum(1 for d in store.list() if d["status"] == "processing")


async def _stream_upload_to_temp(file: UploadFile) -> tuple[Path, str, int]:
    """Streams the multipart upload straight to a temp file on the same
    data-dir filesystem (so the later move into place is a same-filesystem
    atomic rename), never holding the whole file as one Python bytes
    object - a >200MB upload is rejected as soon as it crosses the limit
    mid-stream, not after fully buffering it first. Computes the sha256
    incrementally over the same chunks, and sniffs the PDF magic header
    off the very first chunk before writing anything past it, so an
    obviously-wrong file is rejected almost immediately rather than after
    streaming the whole thing to disk. Returns (temp_path, sha256_hex,
    total_bytes); the caller owns cleaning up temp_path (a move consumes
    it; an early return must unlink it)."""
    fd, tmp_name = tempfile.mkstemp(suffix=".pdf", prefix="upload-", dir=get_data_dir())
    tmp_path = Path(tmp_name)
    hasher = hashlib.sha256()
    total = 0
    max_size = _settings.max_file_size_bytes
    try:
        with os.fdopen(fd, "wb") as f:
            first_chunk = True
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                if first_chunk:
                    if not chunk.startswith(b"%PDF-"):
                        raise HTTPException(400, "File does not look like a PDF (missing %PDF header)")
                    first_chunk = False
                total += len(chunk)
                if total > max_size:
                    raise HTTPException(400, f"File too large (limit {max_size // (1024 * 1024)}MB)")
                hasher.update(chunk)
                f.write(chunk)
        if total == 0:
            raise HTTPException(400, "Empty file")
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path, hasher.hexdigest(), total


@app.post("/api/documents", dependencies=[Depends(_require_admin)])
async def upload_document(file: UploadFile, force: bool = False):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only .pdf files are accepted")
    if _count_processing_documents() >= _MAX_QUEUED_PROCESSING_JOBS:
        raise HTTPException(503, "Too many documents are already processing - please try again shortly")

    tmp_path, sha256, file_size = await _stream_upload_to_temp(file)

    existing = store.find_by_hash(sha256)
    if existing:
        if force:
            return _reprocess_existing(existing, tmp_path)
        tmp_path.unlink(missing_ok=True)
        return JSONResponse(
            status_code=409,
            content={"error": "duplicate", "existingDocument": document_summary_json(existing)},
        )

    doc_id = new_id()
    target = get_pdf_path(doc_id)
    shutil.move(str(tmp_path), str(target))
    try:
        # create_document_if_below_processing_cap (not the plain
        # create_document + the early _count_processing_documents() check
        # above alone) is the actual enforcement point for the queue cap:
        # the count and the insert happen inside one locked transaction,
        # so a burst of concurrent uploads past the early fast-fail check
        # above still can't all squeeze past the cap together (see that
        # method's docstring in db/repository.py for the race it closes).
        doc = store.repo.create_document_if_below_processing_cap(
            doc_id, sha256, file.filename, file_size, _MAX_QUEUED_PROCESSING_JOBS
        )
        if doc is None:
            target.unlink(missing_ok=True)
            raise HTTPException(503, "Too many documents are already processing - please try again shortly")
    except sqlite3.DatabaseError as exc:
        # Two concurrent uploads of the same file can both pass the
        # find_by_hash check before either commits. Depending on sqlite/Python
        # timing, the unique-index violation may surface as IntegrityError or
        # its DatabaseError base class. Only normalize this known constraint.
        if "UNIQUE constraint failed: documents.sha256" not in str(exc):
            target.unlink(missing_ok=True)
            raise
        existing = store.find_by_hash(sha256)
        if existing:
            if force:
                return _reprocess_existing(existing, target)
            target.unlink(missing_ok=True)
            return JSONResponse(
                status_code=409,
                content={"error": "duplicate", "existingDocument": document_summary_json(existing)},
            )
        target.unlink(missing_ok=True)
        raise
    _executor.submit(_run_processing, doc_id)
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


@app.get("/api/departments/divisions")
def get_department_divisions():
    """Flat department->division lookup from the master catalog, for views
    (Dashboard's daily product table) that show Division above Department
    per row without needing a document-scoped division summary. Read-only,
    already-cached mapping - no new computation, just exposing
    get_default_department_to_division_code() (used server-side by
    templates/department_groups.py) to the frontend."""
    from pdf_document_intelligence.templates.department_groups import get_default_department_to_division_code

    return {
        department: {"code": code, "name": name}
        for department, (code, name) in get_default_department_to_division_code().items()
    }


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
    pdf_path = get_pdf_path(doc_id)
    if not pdf_path.is_file():
        raise HTTPException(404, "pdf file missing on disk")
    # FileResponse streams straight from disk instead of get_pdf_bytes()
    # reading the whole file into one Python bytes object first - the
    # response is identical, just without holding a full copy in memory
    # for however long the client takes to receive it.
    return FileResponse(pdf_path, media_type="application/pdf")


@app.post("/api/documents/{doc_id}/reprocess", dependencies=[Depends(_require_admin)])
def reprocess_document(doc_id: str):
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(404, "not found")
    if not get_pdf_path(doc_id).is_file():
        raise HTTPException(404, "pdf file missing on disk")
    # 423 (not 409, same reasoning as delete's guard above): a double
    # click, two tabs, or this racing the force-upload duplicate path
    # (_reprocess_existing) must not submit a second worker job for the
    # same document - two workers concurrently writing the same
    # document's rows/status would corrupt whichever one loses the race.
    # mark_reprocessing() claims the "processing" transition atomically,
    # so this check is race-free even under true concurrency.
    if not store.mark_reprocessing(doc_id):
        raise HTTPException(423, "cannot reprocess a document while it is already processing")
    _executor.submit(_run_processing, doc_id)
    return document_summary_json(store.get(doc_id))


@app.delete("/api/documents/{doc_id}", dependencies=[Depends(_require_admin)])
def delete_document(doc_id: str):
    doc = store.get(doc_id)
    if not doc:
        raise HTTPException(404, "not found")
    if doc["status"] == "processing":
        # 423 (not 409) deliberately: api.js's json() helper treats 409 as
        # a non-error special case (the upload-duplicate flow's contract),
        # which would make this rejection silently look like success on
        # the frontend instead of surfacing the error dialog.
        raise HTTPException(423, "cannot delete a document while it is still processing")
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
    row = store.get_active_product_row(row_id)
    if not row:
        raise HTTPException(404, "not found")
    doc = store.get(row["document_id"])
    return product_row_json(row, doc["filename"] if doc else "")


@app.patch("/api/products/{row_id}", dependencies=[Depends(_require_admin)])
def patch_product(row_id: str, body: dict = Body(...)):
    if not store.get_active_product_row(row_id):
        raise HTTPException(404, "not found")
    field_name = body.get("field")
    if not field_name:
        raise HTTPException(400, "'field' is required")
    try:
        result = review_api.apply_correction(
            store.repo, row_id, field_name, body.get("value"), body.get("reason"),
            body.get("source", "LOCAL_USER"), expected_updated_at=body.get("expectedUpdatedAt"),
        )
    except review_api.RowConflictError as exc:
        # 412 Precondition Failed, not 409 - api.js's json() helper
        # special-cases 409 as a non-error (the upload-duplicate flow's
        # contract), which would make this conflict silently look like a
        # successful save on the frontend. The current row is returned so
        # the client can show what changed instead of just "conflict".
        doc = store.get(exc.current_row["document_id"])
        return JSONResponse(
            status_code=412,
            content={
                "error": "conflict",
                "message": str(exc),
                "currentRow": product_row_json(exc.current_row, doc["filename"] if doc else ""),
            },
        )
    doc = store.get(result["row"]["document_id"])
    return {
        "correctionId": result["correction_id"],
        "row": product_row_json(result["row"], doc["filename"] if doc else ""),
        "propagatedCount": result.get("propagatedCount", 0),
    }


@app.get("/api/products/{row_id}/history")
def product_history(row_id: str):
    # get_any_product_row, not get_active_product_row (PR11): the row's
    # correction history must stay retrievable even after the row itself
    # was soft-deleted (its document was deleted, or it was superseded by
    # a reprocess) - that is the entire point of soft-deleting rather than
    # hard-deleting them. Only the read-only history view needs this;
    # patch/undo above correctly still require an active row.
    if not store.get_any_product_row(row_id):
        raise HTTPException(404, "not found")
    return [
        {
            "id": c["id"], "field": c["field_name"], "oldValue": c["old_value"],
            "newValue": c["new_value"], "reason": c["reason"], "source": c["source"],
            "undoOfId": c["undo_of_id"], "createdAt": c["created_at"],
        }
        for c in store.repo.list_corrections(row_id)
    ]


@app.post("/api/products/{row_id}/undo", dependencies=[Depends(_require_admin)])
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


@app.post("/api/review/{row_id}/confirm", dependencies=[Depends(_require_admin)])
def confirm_review(row_id: str, body: dict = Body(default={})):
    return review_api.confirm_review_row(store.repo, row_id, body.get("source", "LOCAL_USER"))


@app.get("/api/master/local")
def list_local_master(search: str | None = Query(default=None)):
    entries = store.repo.list_local_master(search)
    return {"count": len(entries), "entries": entries}


@app.post("/api/master/local", dependencies=[Depends(_require_admin)])
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


@app.get("/api/master/official/lookup")
def official_master_lookup(barcode: str = Query(..., min_length=1)):
    """A single-barcode existence check against the Official Master, so a
    user can confirm a specific product really imported (the Product Master
    page's search box only searches the small Local Verified list - there is
    still no per-row listing endpoint for the ~35k-row Official Master, this
    is an O(1) dict lookup only, not a new browsing surface)."""
    from pdf_document_intelligence.catalog.loader import get_default_catalog

    entry = get_default_catalog().get(barcode.strip())
    if entry is None:
        return {"found": False}
    return {
        "found": True,
        "barcode": entry.barcode,
        "name": entry.name,
        "structure": entry.structure or None,
        "articleCode": entry.root_code or None,
    }


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


@app.post("/api/master/import", dependencies=[Depends(_require_admin)])
async def import_master_catalog(file: UploadFile):
    import json

    from pdf_document_intelligence.catalog import snapshot as snapshot_module
    from pdf_document_intelligence.catalog.import_validation import MasterImportError, validate_payload

    if not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Only .csv files are accepted")
    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(400, "Empty file")
    if len(csv_bytes) > _MAX_MASTER_IMPORT_BYTES:
        raise HTTPException(400, "File too large (limit 50MB)")

    # Compile and validate the candidate *before* replacing the live
    # snapshot.  The previous implementation imported with overwrite=True
    # first and only then validated/rolled back.  That left a real window
    # where a processing worker could read (and lru-cache) a catalog that
    # was about to be rejected.  A failed import must therefore be a true
    # no-op for the active snapshot, not "write bad data then put the old
    # bytes back".
    snapshot_path = snapshot_module.get_snapshot_path()
    previous_payload = None
    if snapshot_path.is_file():
        try:
            previous_payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous_payload = None

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp.write(csv_bytes)
            tmp_path = Path(tmp.name)
        try:
            candidate_payload = snapshot_module.compile_catalog_payload(tmp_path)
        except FileNotFoundError as exc:
            raise HTTPException(400, "Could not read uploaded file") from exc
        except (OSError, ValueError, UnicodeError) as exc:
            raise HTTPException(400, f"Failed to import catalog: {exc}") from exc

        try:
            warnings = validate_payload(candidate_payload, previous_payload)
        except MasterImportError as exc:
            raise HTTPException(400, str(exc)) from exc

        # Only a validated candidate is allowed to cross the atomic replace
        # boundary.  write_catalog_snapshot() writes/fsyncs a sibling temp
        # file and then Path.replace()s it over the old snapshot.
        snapshot_module.write_catalog_snapshot(candidate_payload, snapshot_path=snapshot_path, overwrite=True)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    _clear_catalog_caches()
    response = _snapshot_status_payload()
    response["warnings"] = warnings
    return response


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


@app.post("/api/backup", dependencies=[Depends(_require_admin)])
def create_backup():
    path = backup_module.create_backup()
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/restore", dependencies=[Depends(_require_admin)])
async def restore_backup(file: UploadFile):
    # Fast up-front rejection so a busy system doesn't spend time reading
    # a (possibly large) upload just to be told no - restore_backup()
    # re-checks this same condition atomically under the write lock right
    # before it mutates anything, which is the actual race-safety
    # guarantee; this check only saves a wasted upload in the common case.
    if any(d["status"] == "processing" for d in store.list()):
        raise HTTPException(423, "cannot restore while a document is still processing")
    data = await file.read()
    try:
        result = backup_module.restore_backup(data)
    except backup_module.RestoreConflictError as exc:
        raise HTTPException(423, str(exc)) from exc
    except backup_module.RestoreError as exc:
        raise HTTPException(400, str(exc)) from exc
    if result.get("masterSnapshotRestored"):
        # The restored master_catalog.snapshot.json is a different file on
        # disk now - the lru_cache'd catalog/department readers must be
        # invalidated the same way a live master import already does them
        # (see _clear_catalog_caches's own docstring), or every extraction
        # and lookup keeps matching against the pre-restore catalog still
        # held in memory.
        _clear_catalog_caches()
    return result


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
