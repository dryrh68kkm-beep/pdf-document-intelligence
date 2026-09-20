# pdf-document-intelligence

Accuracy-first, deterministic PDF document intelligence for local/offline use.
PDFs are parsed with template/rule logic, Official Master matching and
Tesseract OCR fallback — no AI/LLM product inference.

See `docs/APPLICATION.md` for the current application architecture and
`docs/OCR_ROOT_CAUSE.md` for the OCR evidence/root-cause notes.

## Windows setup

1. Install Python 3.11+.
2. Install Tesseract OCR with the Thai language pack (`tha`).
3. Double-click `install.bat`.
4. Start from the **PDF Document Intelligence** Desktop shortcut.

The installer now checks both the Tesseract binary and the Thai language
pack before it reports success.

The Windows launcher starts the existing LAN server on `0.0.0.0:8000`,
waits until `/api/health` is ready, then opens Chrome (or the default
browser). `stop.bat` stops only the server process owned by this app.

## Auto PDF Folder Import

The application watches an inbox folder for new PDFs. A stable new PDF is
SHA-256 deduplicated and fed through the same processing pipeline as
**Add Files**. Results are persisted in SQLite, so a PDF already handled is
not parsed/OCR'd again after an app restart.

Default Windows inbox:

```text
%LOCALAPPDATA%\pdf-document-intelligence\inbox
```

To watch a different existing folder, set:

```text
PDF_INTELLIGENCE_INBOX_DIR=<folder path>
```

The original inbox file is left untouched; the application copies verified
bytes into its managed PDF storage before processing.

## Manual development run

```bash
python -m venv .venv
# activate the environment for your OS
pip install -e ".[api,ocr,dev]"
uvicorn pdf_document_intelligence.api.app:app --host 0.0.0.0 --port 8000
```

## Persistence and data location

Runtime state is SQLite-backed and survives restarts. On Windows the default
application data directory is:

```text
%LOCALAPPDATA%\pdf-document-intelligence
```

It contains `app.db`, managed PDFs, backups and the default inbox.

## Tests

```bash
pytest
```

CI separates:
- Unit + API tests
- Remaining integration regressions
- Golden regression + real OCR
- Concurrency/LAN stress
- Windows smoke/E2E + required Thai OCR

Only synthetic/redacted test fixtures are committed; real PDFs and operational
Master data are excluded from the repository.
