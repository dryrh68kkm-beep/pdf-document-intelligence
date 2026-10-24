# Store Suite — all three programs in one

`store_suite/` combines **PDF Document Intelligence**, **Expiry Dashboard**
(expiry-dashboard) and **Stock Atlas** (Ooslayout) into a single program:
one server, one port (8100; picks the next free one if busy), one launcher, one data hub keyed by barcode.

```text
Windows:  double-click StoreSuite.bat      (first run installs, then starts with NO console window and opens the browser;
                                            StoreSuite_console.bat shows the console; close from ตั้งค่า > ปิด Store Suite or StopStoreSuite.bat)
Mac/Linux: ./StoreSuite.sh
```

The first run of `StoreSuite.bat` also puts a **Store Suite** icon on the Desktop (starts with no console window, log in `%LOCALAPPDATA%\store-suite\last-run.log`; `StopStoreSuite.bat` stops it; starting it twice just reopens the running one).

| Tab | What it is |
|---|---|
| ภาพรวม | a status strip (where each data set came from and when) plus three separate panels - expiry (KPIs, days-left distribution, per-department table, sortable/searchable item list with homes), OOS / Pick Check (KPIs, SOH and result breakdown, filterable list) and PDF documents. Formerly: two separate panels - **สินค้าหมดอายุ** (expiry KPIs + table with the home each item was counted in) and **OOS / Pick Check** (its own KPIs + list). The two data sets are never mixed in one table; only the top search box looks a barcode up across everything |
| วันหมดอายุ | the Expiry Dashboard page, reading the shared `data.csv` |
| ผังร้าน / OOS | Stock Atlas; its LAN-server API is built in, so layout / OOS / Pick Check state is shared by every device |
| เอกสาร PDF | the original PDF app, unchanged, mounted at `/m/pdf/` |

**How they sync** (nothing is copied into a second database):

- Expiry file (`NEARLY_EXPIRED_*` from the network folder set under *ตั้งค่า*, or dropped in by hand) is validated and becomes the one `data.csv`. The dashboard shows it, and the PDF pipeline uses it to confirm barcodes.
- The Expiry page auto-fetches the PDF app's master feed (`/m/pdf/api/export/expiry-dashboard.csv`) to fill blank names/departments.
- The hub joins Atlas count data + OOS state + PDF rows + expiry rows on the barcode: `GET /api/suite/product/{barcode}`, `/api/suite/search?q=`, `/api/suite/expiry-locations`, `/api/suite/overview`.
- *ซิงค์ข้อมูล* (and a background timer, default every 10 min) pulls fresh expiry data and writes `expiry-locations.csv` into Atlas' export folder (`/m/atlas/export/expiry-locations.csv`) for other programs.
- Searching a barcode in the top bar can open it directly in any tab's own search box.

Data lives in `%LOCALAPPDATA%\store-suite` (override: `STORE_SUITE_DATA_DIR`); the PDF app keeps its existing data dir, so current documents carry over. Settings: `config.json` there (or the ตั้งค่า dialog). Only LAN / loopback clients are accepted unless `lanOnly` is turned off.

**Import from the standalone programs.** *ตั้งค่า → ดึงค่าจากโปรแกรมเดิม* looks next to this folder (e.g. `C:\LP-Tools\ExpiryApp`, `C:\LP-Tools\Ooslayout`), reads expiry-dashboard's `config.ps1` (network folder, file name, extensions) and Stock Atlas' `server\config.json` (extra drop folders), and copies the current `data.csv` and Atlas' saved layout / OOS / count / POG state. It never overwrites anything Store Suite already has.

**Accuracy cross-checks (automatic, no manual input).** While reading a PDF, every
row is compared with the other programs' data (`catalog/cross_reference.py`):

- *Names*: an exact barcode hit in the Stock Atlas count database / OOS reports (after Official Master, Local Master and the expiry data) supplies the name instead of OCR (`CROSS_REFERENCE_MATCH`).
- *Barcodes*: a barcode no source knows whose GTIN check digit fails is replaced only if exactly one check-digit-valid known barcode is a single edit away (substitution, swap, missing or extra digit). The original reading stays in `raw_value` (`BARCODE_CROSS_REPAIRED`). A valid-looking unknown barcode is changed only when the printed name also matches (≥ 0.8); otherwise it is just flagged (`BARCODE_SUGGESTION:<code>`, `BARCODE_CHECKSUM_FAIL`, `BARCODE_AMBIGUOUS_NEIGHBORS`) - never guessed.
- On the 21k real barcodes in the Atlas count DB, a simulated one-digit misread was repaired to the right barcode 95% of the time and to a wrong one 0 times (the rest are left for review).
- Inside Store Suite this is wired up by default; standalone, set `PDI_CROSS_REFERENCE_COUNT_FILES` / `PDI_CROSS_REFERENCE_OOS_FILES`.

The expiry page and Atlas are vendored under `store_suite/web/modules/`; refresh them from the sibling repos with `python scripts/sync_modules.py --siblings <folder>`. Tests: `pytest tests/suite`.

---

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
