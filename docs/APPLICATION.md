# Desktop web application — architecture and status

## Current application

**Backend** (`pdf_document_intelligence/api/`):
- `store.py` — in-memory, thread-safe, multi-document store. SHA-256
  dedup on upload; per-document `ProgressState` (stage/current/total)
  updated live during processing.
- `app.py` — FastAPI. Upload runs on a `ThreadPoolExecutor` (2 workers),
  not the request-handling event loop: PDF extraction/OCR is CPU-bound
  Python, so this is the server-side equivalent of a browser Web Worker —
  the API stays responsive to list/detail/export requests while a
  document is mid-pipeline. Endpoints: upload (with `force` dedup
  bypass), list/detail/delete/reprocess, PDF passthrough for the embedded
  viewer, flat cross-document product list, dashboard aggregate, combined
  Excel export.
- `aggregate.py` — cross-document department/KPI aggregation. Only sums
  fields the extracted schema actually has (`weight_qty`/`pu_qty`/`sku_qty`
  for this document type) — **no fabricated price/amount total**, since
  the golden document type (a packing list) doesn't carry monetary values.
  A future invoice-type template with real price/amount fields would
  appear automatically; nothing here assumes those fields exist.
- `serialize.py` — flattens `DocumentResult` into the row-oriented JSON
  the frontend consumes, including full per-field evidence (raw PDF text,
  OCR text + confidence, source, flags) for the review/detail panels.
- `pipeline/orchestrator.py` gained an `on_progress(stage, current, total)`
  callback, threaded through `text_extraction` (per page) and
  `ocr_cross_validation` (per row) — this is what makes the incremental
  "Processing 8/47 pages" UI real progress, not a fake spinner.

**Frontend** (`frontend/app/`): vanilla JS, ES modules, no bundler (Node
is available in this environment but wasn't already part of this Python
project's toolchain, and a full webpack/vite setup for this scope wasn't
worth the added dependency surface). One `index.html` shell; sidebar
switches `view` in JS state, never a page reload. View modules
(`views/*.js`) are lazy-loaded via native dynamic `import()`.

- `state.js` — central store + pub/sub. All views re-render from this on
  any state change.
- Shared pagination components keep product and review tables responsive without rendering an unbounded list.
- `components/detailPanel.js` — right-side product detail + evidence
  (raw PDF / OCR / confidence / reasons), with an embedded PDF viewer
  (`<iframe>` + `#page=N`) fetched from `/api/documents/{id}/pdf`.
- Persistent bottom Add-Files bar + drag-and-drop anywhere on the app
  (dragenter/dragleave depth-counted to handle nested elements correctly).
- Global search debounced 200ms, filtering a search index string
  precomputed once per data refresh (not recomputed per keystroke).

## Master catalog lookup (barcode -> authoritative product name)

`pdf_document_intelligence/catalog/` adds a higher-confidence resolution
path for the `name` field than OCR: `data/master_catalog.csv` (~30k
barcode -> name rows, also the Division rollup's source - see
`templates/department_groups.py`) is loaded once and looked up by
barcode before OCR cross-validation runs. A matched name skips OCR because the Master is authoritative. A match is ground truth — an
exact hit against real master data, not a pixel/glyph reading — so it's
never flagged for review, and it takes priority over OCR. On the golden
sample this resolves 133/154 (86%) of names exactly, vs. OCR's 116/154
legible-but-still-uncertain recoveries; `raw_value`/`ocr_raw_value` are
preserved either way, never overwritten.

`catalog/classify.py` also flags rows suspected of being internal
marketing material or explicit free-gift items (`suspected_non_product`),
using only signals specific enough that a real product can't plausibly
trigger them (an internal `PAQ1_`/`PAQ2_` barcode-name prefix, or the
literal phrase "ของแถม"). An earlier draft used looser keywords (`POP`,
`LABEL`, `STAND`, `TAG`, `"ราคาโปรโมชั่น"`, `"ป้ายห้อย"`) and was rejected
after verification against the real catalog caught it mis-flagging actual
products — `JOHNNIE WALKER GOLD LABEL` (real whisky), a real luggage tag,
and real discounted meat all got wrongly flagged as "not a product". Those
specific cases are pinned as regression tests in
`tests/unit/test_catalog_classify.py`. Flagged rows are never deleted or
silently reclassified — they're grouped into a separate "ของแถม /
ไม่ใช่สินค้า" view instead of counting toward ordinary SKU/quantity totals.

## What's implemented (P0 + most of P1)

- App shell, persistent Add Files bar, drag-and-drop anywhere, duplicate
  (SHA-256) detection with a real "add anyway" bypass.
- Auto-processing on add, live incremental progress per document.
- Dashboard with real KPIs (never a fabricated amount), department bar
  chart, department cards.
- Departments view, Products view (virtualized, searchable, department-
  filterable), Review view (all flagged rows).
- Product detail side panel with full evidence trail + embedded PDF
  viewer jumping to the correct page.
- Documents view: status, reprocess, remove (with confirmation, dashboard
  recalculates immediately).
- Combined Excel export across all completed documents.

Verified end-to-end in a real browser (Playwright): upload → live
progress → dashboard populated with correct real numbers → department
drill-down → product search → detail panel → evidence → embedded PDF at
the right page → review queue → document remove/reprocess → duplicate
dialog, both cancel and confirm paths.

## What's explicitly deferred (P2, or noted limitations)

- **Manual correction / edit-and-save with audit trail** (spec §18-19):
  the Review panel is read-only (view evidence) in this version. Building
  a fake "Confirm" button that doesn't persist would be worse than not
  having it — this needs a real `PATCH` endpoint + correction audit log,
  not implemented yet.
- **IndexedDB / durable persistence**: the document store is in-memory;
  a server restart loses all processed documents. Explicitly P2 in the
  spec's own priority ordering.
- **Keyboard shortcuts, code-splitting beyond dynamic `import()`**: not
  implemented.
- **True background-thread cap / page-parallelism**: processing runs on a
  2-worker thread pool; the proposal's page-parallel worker-pool
  architecture (§50) is still not implemented — OCR-heavy documents take
  ~60s each (11 pages / 154 rows in the golden sample), serialized per
  document.
- **Search is client-side over an in-memory array fetched once per
  refresh** (`GET /api/products`). Fine at the scale tested (154 rows);
  a dataset in the tens of thousands of rows across many documents would
  want server-side pagination/filtering instead of shipping the whole
  array to the browser every refresh.
