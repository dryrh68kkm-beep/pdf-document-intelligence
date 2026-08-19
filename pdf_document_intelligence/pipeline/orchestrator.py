"""pipeline/orchestrator.py: wires PDFLoader -> TextExtractor ->
TableReconstructor -> FieldParser -> ValidationEngine -> ConfidenceEngine
into one `process_document()` call, writing every stage to the shared
processing log (proposal §37).

This is the *slice-1* orchestrator: digital-text PDF, one template, no
OCR/page-parallel worker pool yet (deferred per the agreed vertical-slice
scope) — the page-parallel/queue architecture from proposal §50 slots in
here later without changing the module boundaries above it.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from pdf_document_intelligence.audit.log import ProcessingLog
from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.confidence.engine import score_document
from pdf_document_intelligence.extract.text import extract_document_text
from pdf_document_intelligence.loader.preflight import PreflightError, run_preflight
from pdf_document_intelligence.models.document import DocumentResult, ExtractedTable, ValidationSummary
from pdf_document_intelligence.tables.fields import compute_confidence_band, parse_row
from pdf_document_intelligence.tables.reconstruct import reconstruct_tables
from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS, TEMPLATE_ID, TEMPLATE_VERSION
from pdf_document_intelligence.validate.cross_validate import ThaiOcrCrossValidator
from pdf_document_intelligence.validate.reconciliation import check_duplicate_rows, reconcile_table


def process_document(path: Path, settings: Settings | None = None, enable_ocr: bool = True) -> DocumentResult:
    settings = settings or Settings()
    log = ProcessingLog()
    doc_id = str(uuid.uuid4())

    with log.step("preflight", f"checking {path.name}"):
        try:
            preflight = run_preflight(path, settings)
        except PreflightError as exc:
            log.record("preflight", f"FAILED {exc.code}: {exc}")
            return DocumentResult(
                id=doc_id,
                filename=path.name,
                pages=0,
                document_type=None,
                engine_version=settings.engine_version,
                ocr_engine_version=settings.ocr_engine_version,
                parser_version=settings.parser_version,
                template_version=None,
                confidence=0.0,
                status="MANUAL_REVIEW_REQUIRED",
                validation=ValidationSummary(reconciled=False, errors=[]),
                processing_log=log.entries,
            )

    with log.step("text_extraction", "pdfplumber word/bbox extraction + quality scoring"):
        doc_text = extract_document_text(path, settings)
        unreliable_pages = [p.page_number for p in doc_text.pages if not p.quality.reliable]
        log.record(
            "text_extraction",
            f"{len(doc_text.pages)} pages; text-layer unreliable on pages {unreliable_pages}"
            if unreliable_pages
            else f"{len(doc_text.pages)} pages; text layer reliable throughout",
        )

    with log.step("table_reconstruction", "geometric column/row assignment"):
        raw_tables = reconstruct_tables(doc_text)
        log.record("table_reconstruction", f"{len(raw_tables)} department tables detected")

    quality_by_page = {p.page_number: p.quality for p in doc_text.pages}
    extracted_tables: list[ExtractedTable] = []
    with log.step("field_parsing", "typed FieldValue assignment + Thai normalization"):
        for raw in raw_tables:
            group_carry: dict[str, str] = {}
            rows = [
                parse_row(raw_row, idx, quality_by_page, settings, group_carry)
                for idx, raw_row in enumerate(raw.rows, start=1)
            ]
            extracted_tables.append(
                ExtractedTable(
                    name=raw.department,
                    page_start=raw.page_start,
                    page_end=raw.page_end,
                    header=[c.canonical_name for c in COLUMNS],
                    rows=rows,
                    source_pages=list(range(raw.page_start, raw.page_end + 1)),
                )
            )
        total_rows = sum(len(t.rows) for t in extracted_tables)
        log.record("field_parsing", f"{total_rows} rows parsed across {len(extracted_tables)} tables")

    ocr_engine_version = settings.ocr_engine_version
    if enable_ocr:
        with log.step("ocr_cross_validation", "selective region-level OCR for Thai fields on unreliable pages"):
            validator = ThaiOcrCrossValidator(path, settings)
            for table in extracted_tables:
                for row in table.rows:
                    updated = {
                        name: validator.maybe_apply(field, quality_by_page[field.bbox.page])
                        for name, field in row.fields.items()
                    }
                    row.fields = updated
                    row.confidence_band = compute_confidence_band(updated)
            from pdf_document_intelligence.extract.ocr import clear_page_cache

            clear_page_cache()
            log.record("ocr_cross_validation", f"{validator.ocr_calls} region OCR calls")
            if validator.ocr_calls:
                ocr_engine_version = "tesseract-5.3.4 (tha+eng)"

    with log.step("validation", "department-level reconciliation + duplicate detection"):
        errors = []
        warnings = []
        for raw, table in zip(raw_tables, extracted_tables):
            for issue in reconcile_table(table, raw, settings):
                (errors if issue.severity == "error" else warnings).append(issue)
            for issue in check_duplicate_rows(table):
                (errors if issue.severity == "error" else warnings).append(issue)
        reconciled = not errors
        validation = ValidationSummary(reconciled=reconciled, errors=errors, warnings=warnings)
        log.record(
            "validation",
            f"reconciled={reconciled}; {len(errors)} errors, {len(warnings)} warnings",
        )

    with log.step("confidence_scoring", "composite document confidence + status"):
        confidence, status = score_document(extracted_tables, validation, settings)
        log.record("confidence_scoring", f"confidence={confidence:.2f}% status={status}")

    return DocumentResult(
        id=doc_id,
        filename=path.name,
        pages=preflight.page_count,
        document_type=TEMPLATE_ID,
        engine_version=settings.engine_version,
        ocr_engine_version=ocr_engine_version,
        parser_version=settings.parser_version,
        template_version=TEMPLATE_VERSION,
        confidence=confidence,
        status=status,
        tables=extracted_tables,
        fields=[],
        validation=validation,
        processing_log=log.entries,
    )
