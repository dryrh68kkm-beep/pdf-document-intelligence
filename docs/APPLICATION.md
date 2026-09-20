# Desktop web application — current architecture

## Runtime model

PDF Document Intelligence is a local/offline FastAPI + SQLite application.
The browser frontend is a single-page vanilla-JS app served by the same
process. The normal Windows launcher binds the server to `0.0.0.0:8000`
for LAN use and opens the browser only after the health endpoint is ready.

Processing is deterministic. Product resolution uses PDF extraction,
registered templates, validation/reconciliation, Official Master exact
matching, Local Verified corrections, and Tesseract OCR fallback. The app
does not use an LLM/Generative-AI inference path.

## Backend

### SQLite persistence

`pdf_document_intelligence/db/` is the durable system of record:

- WAL mode + foreign keys + busy timeout.
- A process-wide write lock serializes write transactions on the shared
  connection.
- Documents, extracted product rows, correction history and Local Verified
  Master survive application restarts.
- SHA-256 is used for document deduplication.
- Optimistic row updates protect concurrent corrections from stale overwrite.

On Windows the default data directory is
`%LOCALAPPDATA%\pdf-document-intelligence`, unless
`PDF_INTELLIGENCE_DATA_DIR` overrides it.

### Processing

`api/app.py` submits PDF work to a small `ThreadPoolExecutor`; API reads
remain responsive while parsing/OCR runs. The processing backlog has an
atomic SQLite-backed admission cap so concurrent uploads cannot grow an
unbounded queue.

A process restart recovers documents left in an interrupted
`processing` state instead of leaving them permanently locked.

### Auto PDF Folder Import

`api/inbox_watcher.py` watches the inbox approximately every seven seconds
(default, configurable). It:

1. waits until file size + modified time are stable across scans;
2. rejects empty, oversized, invalid-signature and symlink candidates;
3. hashes the stable source with SHA-256;
4. skips any hash already represented in SQLite, including a previously
   removed document;
5. copies the PDF into app-managed storage while hashing the copied bytes
   again, preventing a source-change race;
6. submits the same processing pipeline used by manual **Add Files**.

The default inbox is `<data-dir>/inbox`.
`PDF_INTELLIGENCE_INBOX_DIR` can point the watcher at another folder.
An unavailable custom inbox no longer prevents the rest of the app from
starting; watcher status reports the folder as unavailable and retries.

### Backup / restore

Full backups contain:
- a consistent SQLite snapshot;
- managed source PDFs;
- the compiled Master snapshot when present;
- checksums and backup metadata.

Restore validates the archive before mutation, stages the restored files,
then swaps DB/PDF/Master state under the write lock. If an activation step
fails, the old DB and file assets are restored rather than leaving a
partially-restored installation.

### Health

`GET /api/health` checks:
- database/schema;
- Official and Local Master status;
- Tesseract binary;
- Thai OCR language pack;
- writable data/temp directories;
- free disk space.

Raw exception details and secrets are not returned by the health endpoint.

## Frontend

`frontend/app/` uses ES modules and dynamic view loading. Current primary
views include Dashboard, Departments, Products, Review, Focus Items,
Non-product, Documents and Product Master.

Shared state preserves document/date filtering, search/pagination behavior
and background refresh behavior. Dashboard KPI document/row counts are
derived from the same date-scoped document/product sets used by the other
views; a failed per-document Division summary is surfaced as incomplete
instead of silently shrinking those headline counts.

## Product Master

Official Master is read-only reference data used for exact barcode
resolution. Local Verified Master stores user-corrected product knowledge.
Runtime Master import validates the candidate before atomically replacing
the active snapshot and clears in-process catalog caches only after a valid
replacement.

## Windows operation

`install.bat` requires:
- Python 3.11+;
- Tesseract;
- the `tha` Tesseract language pack.

`scripts/run_server.py` owns a PID file in the app data directory, starts
Uvicorn, waits for `/api/health`, and then opens Chrome/default browser.
`stop.bat` verifies both the recorded process command line and ownership
of port 8000 before terminating it, so an unrelated application on the same
port is not killed.

## CI / regression coverage

The workflow gates:
- Unit + API tests;
- non-OCR integration regressions (backup/restore, dashboard date
  consistency, export cleanup, inbox import, Master import);
- Golden regression + real OCR;
- LAN/concurrency stress;
- Windows smoke/E2E;
- required Windows Thai OCR.

Synthetic/runtime-generated PDFs are used in tests. Operational PDFs and
Master datasets are excluded by repository data-safety tests.

## Current limits

- Product/search data is still primarily fetched client-side; very large
  datasets may eventually benefit from server-side pagination/filtering.
- PDF processing uses a small document-level worker pool rather than
  page-parallel OCR.
- Viewer/Admin is an optional shared-passphrase gate, not a per-user account
  system.
- Windows CI validates the application and OCR stack, but organization/repo
  policy such as GitHub branch protection remains an external repository
  setting rather than application code.
