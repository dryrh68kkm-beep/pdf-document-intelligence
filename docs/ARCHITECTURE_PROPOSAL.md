# PDF Document Intelligence Pipeline — Architecture Proposal (v0.1, draft for review)

Status: **draft — not yet implemented**. This document exists to be argued with before any pipeline code is written, per the "ก่อนเริ่ม Coding" checklist. Nothing here is final until you sign off.

## 1. Guiding principle (restated, so it's traceable back to every design choice below)

> **Correctness > Traceability > Validation > Recoverability > Performance > Convenience.**
> "ไม่แน่ใจ = ห้ามเดา" — every extracted value must be able to answer "where in the PDF did this come from?", or it cannot be auto-approved.

Every section below exists to serve one of those five ranked priorities, in that order. Where speed and correctness trade off, correctness wins — full stop.

## 2. Constraints from your spec (as scoping decisions, not aspirations)

- No LLM as source-of-truth for numbers/codes/amounts — AI (if used at all) is restricted to classification/semantic mapping/layout interpretation, never numeric value generation. Every numeric field must resolve to a PDF bounding box.
- Must handle high volume in production, not just single-document demos.
- Must handle Thai text correctly (NFC normalization, sara/vowel-mark reassembly, Thai/Arabic digits, ฿, พ.ศ./ค.ศ. dates) as a first-class requirement, not an afterthought.
- Must never silently "fix" ambiguous OCR output (e.g. `1O0` → `100`) without recording the correction as an auditable event.
- Everything configurable (confidence thresholds, tolerances, weights, schema, page/file limits) — no hard-coded magic numbers.

## 3. Tech stack proposal

**Language: Python 3.12**, as agreed. Rationale specific to this domain:

| Concern | Library | Why |
|---|---|---|
| PDF structure / preflight | `pikepdf` (qpdf bindings) | Robust against malformed/corrupted PDFs, encryption, object-stream inspection — better than pypdf for the "hostile input" preflight checks in §4 below |
| Text + coordinate extraction | `pdfplumber` (built on `pdfminer.six`) | Per-character bounding boxes, font info, native table-guessing as a *hint* (not authority) |
| Rendering pages to images (for OCR/QA) | `PyMuPDF` (`fitz`) | Fast, accurate DPI-controlled rasterization; also a cross-check source for text extraction (dual-extraction, §11 of your spec) |
| OCR engine | `PaddleOCR` (primary) with `Tesseract` as a secondary/cross-check engine | PaddleOCR has materially better Thai-script accuracy than Tesseract in practice; running both on low-confidence regions gives a real dual-source check, not a fake one |
| Image preprocessing | `opencv-python` | Deskew, denoise, adaptive threshold, orientation detection |
| Thai text normalization | `pythainlp` (normalization utilities) + custom NFC/zero-width/Thai-digit rules | Purpose-built for exactly the sara/tone-mark reordering problem described |
| Table geometry | custom (see §7) on top of `pdfplumber` word boxes | The spec explicitly requires geometry-driven reconstruction, not a black-box table library — off-the-shelf table detectors (Camelot/Tabula) are line-based and fail on borderless/irregular tables, so we build column-boundary detection ourselves and treat any library output as one *signal*, not the answer |
| Excel export | `openpyxl` | Explicit control over cell number formats — required to preserve leading zeros, Thai text, and decimals exactly (`openpyxl` writes strings as strings unless we say otherwise, which is what we want) |
| API/backend | `FastAPI` | Async, typed (pydantic models double as the schema for §62–63 data model), plays well with a page-parallel worker pool |
| Task queue / page-parallel processing | `Celery` + Redis, or `arq` (lighter, asyncio-native) | Needed for §50 (page-parallel workers, aggregate, validate) — recommend `arq` unless you already run Redis/Celery infra elsewhere |
| Storage | Postgres (metadata, audit trail, confidence scores, corrections) + object storage (S3-compatible) for source PDFs, rendered page images, and OCR intermediates | Postgres gives us transactional audit trail (§36–37) and JSON columns for the flexible per-field confidence data (§28–33) |
| Review UI | React (Vite) split-screen PDF viewer (`pdf.js` or `react-pdf`) + data grid, talking to the FastAPI backend | Client requirement is explicit (§34): PDF pane + data pane + click-to-highlight |
| Sandboxing untrusted PDFs (§54) | Process-level isolation (separate worker process/container per document, resource limits via `resource` module or container cgroups) + PDF preflight rejecting decompression-bomb-shaped files before full parse | We are not going to invent a bespoke sandbox; container-level CPU/RAM/timeout limits plus preflight rejection covers the realistic threat model for this input type |

**What I'm explicitly *not* proposing**: any hosted/third-party OCR or LLM API as a hard dependency for the core pipeline. If you want a hosted OCR (e.g. for handwriting) later, that's an additive engine behind the same `OCRService` interface — not a redesign.

## 4. Pipeline shape

This matches your spec's flow closely; the point of writing it out is to nail down *where module boundaries are* (this becomes the package layout in §11).

```
Upload
  → PDFLoader          (open, preflight: mime/signature/version/pages/size/rotation/
                         encryption/corruption/fonts/text-layer presence, per §2)
  → DocumentClassifier  (digital / scanned / form / mixed — whole-file hint only,
                         never authoritative — see §5)
  → PageClassifier      (per-page: DIGITAL_TEXT / SCANNED_TEXT / IMAGE / TABLE-heavy /
                         FORM / MIXED / UNKNOWN, independently per page)
  → TextExtractor       (pdfplumber word/char boxes; ALSO validates text-layer quality
                         — printable ratio, Thai validity, replacement chars, etc.)
  → LayoutAnalyzer       (segment page into HEADER/BODY/TABLE/SIDEBAR/FOOTER/PAGE_NUMBER/
                         ANNOTATION regions; builds Reading Order from region + geometry)
  → OCRService          (only for pages/regions that need it, per PageClassifier +
                         TextExtractor quality signal; page/region-scoped, not file-wide)
  → TableDetector        (find table regions per page)
  → TableReconstructor   (geometric column/row inference, multi-line cells, wrapped
                         rows, multi-page table stitching)
  → FieldParser          (assign tokens to canonical schema fields via TemplateMatcher
                         or generic header-alias mapping)
  → ThaiNormalizer / TypeParser
                         (NFC normalization, number/date/currency/code parsing —
                         raw_value always preserved alongside parsed_value)
  → ValidationEngine     (business rules: qty×price≈amount, subtotal+tax≈total,
                         cross-row checks, document-level reconciliation)
  → ConfidenceEngine     (composite score: extraction + OCR + layout + schema +
                         type + validation, weighted & configurable)
  → ReviewService        (exception queue, split-screen UI, correction audit)
  → ExportService        (Excel: Data / Validation Issues / Summary / Audit sheets)
  → AuditService         (cross-cutting: every module writes to a shared processing
                         log per document, §37)
```

## 5. Package layout (Python)

```
pdf_document_intelligence/
  loader/            PDFLoader — open, preflight, per-page metadata extraction
  classify/
    document.py      DocumentClassifier (whole-file hint)
    page.py          PageClassifier (per-page, authoritative)
  extract/
    text.py          TextExtractor (+ text-layer quality validation)
    ocr.py            OCRService (page/region-scoped, multi-engine, confidence)
  layout/
    regions.py        LayoutAnalyzer — HEADER/BODY/TABLE/SIDEBAR/FOOTER/... segmentation
    reading_order.py  Reading order engine, built on regions + geometry
  tables/
    detect.py          TableDetector
    reconstruct.py      TableReconstructor (columns, rows, cells, multi-page stitching)
    headers.py          Header detection + alias mapping
  normalize/
    thai.py             ThaiNormalizer (NFC, sara/vowel, zero-width, digits, ฿)
    types.py            TypeParser (number/date/currency/code, locale-aware)
    ambiguity.py         OCR-confusable-character detection + context-aware candidates
                          (never auto-applies — always logged as a correction event)
  templates/
    matcher.py           TemplateMatcher (document fingerprinting)
    fingerprint.py
    versioning.py         Template version registry — old templates immutable once used
  validate/
    business_rules.py    Configurable per-document-type rule engine
    reconciliation.py     Document-level total reconciliation
    dedupe.py              Cross-source (text-extraction vs OCR) duplicate row detection
  confidence/
    engine.py             Composite confidence scoring (field/row/document level)
    thresholds.py          Configuration-driven threshold bands
  review/
    api.py                 FastAPI endpoints for the review UI
    audit.py                Manual-correction audit trail (append-only)
  export/
    excel.py                4-sheet Excel export (Data/Issues/Summary/Audit)
  pipeline/
    orchestrator.py        Wires the above into the page-parallel → aggregate →
                            validate → review flow (§50); owns the processing log
  audit/
    log.py                  Structured processing-log writer, shared by every module
  models/
    document.py             Document/Page/Table/Field/Confidence pydantic models (§62-63)
  config/
    settings.py              All thresholds/weights/limits — pydantic-settings,
                              env-var overridable, never hard-coded in logic
```

`api/` (FastAPI app), `worker/` (arq task definitions), and `frontend/` (React review UI) sit alongside `pdf_document_intelligence/` as separate top-level directories — the library itself has no web/queue dependency, so it stays testable in isolation.

Nothing here is a single god-file — every stage from your §71 module list gets its own file/subpackage, consistent with "ห้ามเขียนทั้งหมดรวมอยู่ในไฟล์เดียว".

## 6. Data model (concrete pydantic sketch, matches your §62–63)

```python
class BoundingBox(BaseModel):
    x: float; y: float; width: float; height: float; page: int

class FieldValue(BaseModel):
    name: str                       # canonical schema field, e.g. "amount"
    raw_value: str                  # exactly as read, pre-parse
    value: str | int | float | None # parsed value, None if unparseable
    type: Literal["string","integer","decimal","currency","percentage",
                   "date","time","datetime","code","boolean"]
    bbox: BoundingBox
    source: Literal["pdf_text","ocr","cross_validated"]
    confidence: float               # 0.0-1.0, composite (see ConfidenceEngine)
    validation_flags: list[str]     # e.g. ["CALCULATION_MISMATCH"]
    review_required: bool
    correction: CorrectionEvent | None = None   # set only if a human edited it

class CorrectionEvent(BaseModel):
    original_value: str; corrected_value: str
    user: str; timestamp: datetime; reason: str | None

class TableRow(BaseModel):
    row_index: int
    fields: dict[str, FieldValue]
    confidence_band: Literal["HIGH","MEDIUM","LOW"]

class ExtractedTable(BaseModel):
    page_start: int; page_end: int
    header: list[str]
    rows: list[TableRow]
    source_pages: list[int]          # for multi-page-table provenance

class DocumentResult(BaseModel):
    id: str; filename: str; pages: int
    document_type: str | None        # from TemplateMatcher, None if UNKNOWN_LAYOUT
    engine_version: str; ocr_engine_version: str
    parser_version: str; template_version: str | None
    confidence: float
    status: Literal["AUTO_APPROVED","REVIEW_RECOMMENDED","MANUAL_REVIEW_REQUIRED"]
    tables: list[ExtractedTable]
    fields: list[FieldValue]         # non-tabular fields (doc number, date, etc.)
    validation: ValidationSummary
    processing_log: list[ProcessingLogEntry]
```

This is a starting sketch, not a locked schema — but it's the shape I'd start coding against.

## 7. The two hardest parts, and how I'd de-risk them early

1. **Geometric table reconstruction without relying on library "guess table" output.** This is genuinely the highest-risk, highest-effort module in the whole system (§12–19 of your spec, roughly a third of the total complexity). I'd build this incrementally against the golden dataset (§8 below), starting with ruled tables, then borderless, then multi-page, each as a separate milestone with its own accuracy metric — not as one big table engine written up front.
2. **Confidence scoring that's actually meaningful**, not a single OCR number relabeled. The weighted composite in §28 needs real calibration against labeled data before the thresholds mean anything — I'd treat the initial threshold values (95/85, 98/90) as placeholders to be tuned once we have the golden dataset's actual accuracy numbers, not ship them as-is.

## 8. Testing / golden dataset strategy

- `tests/unit/` — one test module per `normalize/`, `tables/`, `confidence/` file (Thai normalization, number/date parsing, header alias mapping, reconciliation math — all pure-function-testable without a real PDF).
- `tests/golden/` — a checked-in (or LFS/external-storage-referenced, TBD based on file sizes) set of PDFs per your §42 list (digital, scan, low-quality scan, rotated, Thai/English/mixed, ruled/borderless/multi-page/merged-cell tables, negative numbers, large docs), each with an `expected.json`. A regression runner diffs current pipeline output against `expected.json` and reports Field/Row/Table/Document accuracy (§43–45) — this is the release gate (§69), not an afterthought.
- `tests/integration/` — PDF in → `DocumentResult` out, no mocking of internal stages.
- `tests/e2e/` — upload → extract → review-correction → export, against the FastAPI app.

## 9. What I need from you before implementation starts

1. Sign-off on the stack in §3 (Python/FastAPI/Postgres/PaddleOCR/pdfplumber+PyMuPDF/arq) — or redirections.
2. A first real sample document (even one representative PDF, ideally with a known-correct expected output) to seed the golden dataset and pick the first template to build against — building against zero real documents risks over-fitting to imagined layouts.
3. Confirmation of the **first vertical slice** scope: I'd propose *digital-text PDF → text+coordinate extraction → single ruled table → canonical schema mapping → reconciliation → Excel export*, deliberately deferring OCR, the review UI, and template versioning to slice 2+. This gets the core data model, confidence architecture, and audit trail working end-to-end fastest, on the least risky input type, before tackling OCR/table-geometry complexity.

Nothing past this point gets implemented until you respond to #1–3.
