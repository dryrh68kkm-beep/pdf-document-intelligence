"""pipeline/orchestrator.py: wires PDFLoader -> TextExtractor -> template
detection -> TableReconstructor -> FieldParser -> ValidationEngine ->
ConfidenceEngine into one `process_document()` call, writing every stage
to the shared processing log (proposal §37).

Two templates are registered (templates/packing_list_bigc.py,
templates/packing_list_bpdc.py) with genuinely different table structure
(one department per page vs. Department as an inline column grouped by
pallet block) — template detection picks the right reconstruction +
reconciliation path per document; everything downstream of "a list of
ExtractedTable" (OCR cross-validation, catalog lookup, confidence scoring)
is template-agnostic since both templates share canonical field names.

This is the *slice-1* orchestrator: digital-text PDFs, no page-parallel
worker pool yet (deferred per the agreed vertical-slice scope) — the
page-parallel/queue architecture from proposal §50 slots in here later
without changing the module boundaries above it.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[str, int, int], None]  # (stage_label, current, total)

from pdf_document_intelligence.audit.log import ProcessingLog
from pdf_document_intelligence.catalog.apply import apply_catalog_to_row
from pdf_document_intelligence.catalog.loader import get_default_catalog
from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.confidence.engine import score_document
from pdf_document_intelligence.extract.document_date import extract_document_date
from pdf_document_intelligence.extract.text import extract_document_text
from pdf_document_intelligence.loader.preflight import PreflightError, run_preflight
from pdf_document_intelligence.models.document import DocumentResult, ExtractedTable, TableRow, ValidationSummary
from pdf_document_intelligence.tables.fields import compute_confidence_band, parse_row
from pdf_document_intelligence.tables.reconstruct import reconstruct_tables as reconstruct_bigc
from pdf_document_intelligence.tables.reconstruct_bpdc import reconstruct_tables as reconstruct_bpdc
from pdf_document_intelligence.templates.detect import UNKNOWN_TEMPLATE, detect_template
from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS as BIGC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bigc import TEMPLATE_ID as BIGC_TEMPLATE_ID
from pdf_document_intelligence.templates.packing_list_bigc import TEMPLATE_VERSION as BIGC_TEMPLATE_VERSION
from pdf_document_intelligence.templates.packing_list_bpdc import COLUMNS as BPDC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bpdc import TEMPLATE_ID as BPDC_TEMPLATE_ID
from pdf_document_intelligence.templates.packing_list_bpdc import TEMPLATE_VERSION as BPDC_TEMPLATE_VERSION
from pdf_document_intelligence.validate.coverage import validate_bigc_coverage, validate_bpdc_coverage
from pdf_document_intelligence.validate.cross_validate import ThaiOcrCrossValidator
from pdf_document_intelligence.validate.reconciliation import check_duplicate_rows, reconcile_table
from pdf_document_intelligence.validate.reconciliation_bpdc import reconcile_pallet_block


def process_document(
    path: Path,
    settings: Settings | None = None,
    enable_ocr: bool = True,
    enable_catalog: bool = True,
    on_progress: ProgressCallback | None = None,
) -> DocumentResult:
    settings = settings or Settings()
    log = ProcessingLog()
    doc_id = str(uuid.uuid4())
    progress = on_progress or (lambda stage, current, total: None)

    with log.step("preflight", f"checking {path.name}"):
        try:
            preflight = run_preflight(path, settings)
        except PreflightError as exc:
            # A preflight rejection (corrupted file, password-protected,
            # wrong signature, too many pages, ...) means no page of this
            # document was ever read - it is not the same situation as a
            # document that *was* processed but scored low confidence
            # (MANUAL_REVIEW_REQUIRED, assigned by confidence/engine.py
            # further down this same pipeline). Returning a fake "empty but
            # successful" DocumentResult here used to conflate the two: the
            # document landed in the DB as status='complete' with 0 pages
            # and 0 confidence, showing as a normal ready-to-use document
            # in the UI instead of the actual failure. Letting PreflightError
            # propagate lets the caller's existing failed-processing path
            # (_run_processing -> store.set_error) mark it status='error'
            # with the real reason, exactly like any other processing
            # failure - no new status value or code path needed.
            log.record("preflight", f"FAILED {exc.code}: {exc}")
            raise

    with log.step("text_extraction", "pdfplumber word/bbox extraction + quality scoring"):
        doc_text = extract_document_text(
            path, settings, on_page_done=lambda cur, total: progress("อ่านหน้า PDF", cur, total)
        )
        unreliable_pages = [p.page_number for p in doc_text.pages if not p.quality.reliable]
        log.record(
            "text_extraction",
            f"{len(doc_text.pages)} pages; text-layer unreliable on pages {unreliable_pages}"
            if unreliable_pages
            else f"{len(doc_text.pages)} pages; text layer reliable throughout",
        )

    document_date = extract_document_date(doc_text)
    if document_date:
        log.record("document_date", f"{document_date.label}: {document_date.value.isoformat()} (page {document_date.page})")
    else:
        log.record("document_date", "no explicitly labelled document date found")

    with log.step("template_detection", "matching header signature against registered templates"):
        template_id = detect_template(doc_text)
        log.record("template_detection", f"detected: {template_id}")

    quality_by_page = {p.page_number: p.quality for p in doc_text.pages}
    extracted_tables: list[ExtractedTable] = []
    template_version: str | None = None

    if template_id == UNKNOWN_TEMPLATE:
        log.record("table_reconstruction", "no registered template matched this document's header row")
        validation = ValidationSummary(reconciled=False, errors=[])
        confidence, status = 0.0, "MANUAL_REVIEW_REQUIRED"
        return DocumentResult(
            id=doc_id,
            filename=path.name,
            pages=preflight.page_count,
            document_type=UNKNOWN_TEMPLATE,
            engine_version=settings.engine_version,
            ocr_engine_version=settings.ocr_engine_version,
            parser_version=settings.parser_version,
            template_version=None,
            confidence=confidence,
            status=status,
            tables=[],
            fields=[],
            validation=validation,
            processing_log=log.entries,
            document_date=document_date.value if document_date else None,
            document_date_raw=document_date.raw_value if document_date else None,
            document_date_label=document_date.label if document_date else None,
            document_date_page=document_date.page if document_date else None,
        )

    if template_id == BIGC_TEMPLATE_ID:
        template_version = BIGC_TEMPLATE_VERSION
        with log.step("table_reconstruction", "geometric column/row assignment (packing_list_bigc)"):
            raw_tables = reconstruct_bigc(doc_text)
            log.record("table_reconstruction", f"{len(raw_tables)} department tables detected")

        with log.step("field_parsing", "typed FieldValue assignment + Thai normalization"):
            for raw in raw_tables:
                group_carry: dict[str, str] = {}
                rows = [
                    parse_row(raw_row, idx, quality_by_page, settings, group_carry, columns=BIGC_COLUMNS)
                    for idx, raw_row in enumerate(raw.rows, start=1)
                ]
                extracted_tables.append(
                    ExtractedTable(
                        name=raw.department,
                        page_start=raw.page_start,
                        page_end=raw.page_end,
                        header=[c.canonical_name for c in BIGC_COLUMNS],
                        rows=rows,
                        source_pages=list(range(raw.page_start, raw.page_end + 1)),
                    )
                )
            total_rows = sum(len(t.rows) for t in extracted_tables)
            log.record("field_parsing", f"{total_rows} rows parsed across {len(extracted_tables)} tables")
            progress("สร้างรายการสินค้า", total_rows, total_rows)

        reconcile_stage_label = "coverage + department-level reconciliation + duplicate detection"
        block_rows_for_reconcile = list(zip(raw_tables, extracted_tables))

    else:  # BPDC_TEMPLATE_ID
        template_version = BPDC_TEMPLATE_VERSION
        with log.step("table_reconstruction", "pallet-block scan across the document (packing_list_bpdc)"):
            pallet_blocks = reconstruct_bpdc(doc_text)
            log.record("table_reconstruction", f"{len(pallet_blocks)} pallet blocks detected")

        with log.step("field_parsing", "typed FieldValue assignment + Thai normalization"):
            block_rows: list[tuple[object, list[TableRow]]] = []
            dept_rows: dict[str, list[TableRow]] = defaultdict(list)
            dept_pages: dict[str, set[int]] = defaultdict(set)
            for block in pallet_blocks:
                group_carry = {}
                rows = [
                    parse_row(raw_row, idx, quality_by_page, settings, group_carry, columns=BPDC_COLUMNS)
                    for idx, raw_row in enumerate(block.rows, start=1)
                ]
                block_rows.append((block, rows))
                for row in rows:
                    dept_val = row.fields["department"].value or "UNKNOWN"
                    dept_rows[str(dept_val)].append(row)
                    dept_pages[str(dept_val)].add(row.fields["name"].bbox.page)

            for dept_name in sorted(dept_rows):
                rows = dept_rows[dept_name]
                renumbered = [row.model_copy(update={"row_index": i}) for i, row in enumerate(rows, start=1)]
                pages = sorted(dept_pages[dept_name])
                extracted_tables.append(
                    ExtractedTable(
                        name=dept_name,
                        page_start=pages[0],
                        page_end=pages[-1],
                        header=[c.canonical_name for c in BPDC_COLUMNS],
                        rows=renumbered,
                        source_pages=pages,
                    )
                )
            total_rows = sum(len(t.rows) for t in extracted_tables)
            log.record(
                "field_parsing",
                f"{total_rows} rows parsed across {len(pallet_blocks)} pallet blocks, "
                f"regrouped into {len(extracted_tables)} department tables",
            )
            progress("สร้างรายการสินค้า", total_rows, total_rows)

        reconcile_stage_label = "coverage + pallet-block reconciliation + duplicate detection"
        block_rows_for_reconcile = block_rows

    # Resolve exact barcode matches before OCR.  An Official Master name is
    # authoritative, so it never needs expensive pixel OCR; this is especially
    # important for large Thai documents where hundreds of rows may otherwise
    # spawn Tesseract calls.  Classification stays after OCR so an unmatched
    # row can still benefit from OCR-recovered text.
    catalog = get_default_catalog() if enable_catalog else None
    matched = 0
    if catalog is not None:
        with log.step("catalog_lookup", "Official Master barcode lookup before OCR"):
            for table in extracted_tables:
                table.rows = [apply_catalog_to_row(row, catalog, classify=False) for row in table.rows]
            matched = sum(
                row.fields["name"].source == "master_catalog"
                for table in extracted_tables for row in table.rows
            )
            progress("ตรวจสอบ Official Master", matched, total_rows)
            log.record("catalog_lookup", f"{matched}/{total_rows} rows matched catalog before OCR")

    ocr_engine_version = settings.ocr_engine_version
    if enable_ocr:
        with log.step("ocr_cross_validation", "selective region-level OCR for unresolved Thai fields"):
            validator = ThaiOcrCrossValidator(path, settings)
            all_rows = [row for table in extracted_tables for row in table.rows]
            for i, row in enumerate(all_rows, start=1):
                updated = {
                    name: validator.maybe_apply(field, quality_by_page[field.bbox.page])
                    for name, field in row.fields.items()
                }
                row.fields = updated
                row.confidence_band = compute_confidence_band(updated)
                progress("ตรวจภาษาไทยด้วย OCR", i, len(all_rows))
            from pdf_document_intelligence.extract.ocr import clear_page_cache

            clear_page_cache()
            log.record("ocr_cross_validation", f"{validator.ocr_calls} region OCR calls")
            if validator.ocr_calls:
                ocr_engine_version = "tesseract-5.3.4 (tha+eng)"

    if catalog is not None:
        with log.step("classification", "non-product classification after OCR/master resolution"):
            flagged = 0
            for table in extracted_tables:
                new_rows = []
                for row in table.rows:
                    updated_row = apply_catalog_to_row(row, catalog)
                    if updated_row.suspected_non_product:
                        flagged += 1
                    new_rows.append(updated_row)
                table.rows = new_rows
            log.record(
                "classification",
                f"{matched}/{total_rows} rows matched catalog; {flagged} flagged as suspected non-product",
            )

    with log.step("validation", reconcile_stage_label):
        errors = []
        warnings = []

        if template_id == BIGC_TEMPLATE_ID:
            coverage_issues = validate_bigc_coverage(
                doc_text,
                expected_page_count=preflight.page_count,
                raw_tables=raw_tables,
                extracted_tables=extracted_tables,
            )
        else:
            coverage_issues = validate_bpdc_coverage(
                doc_text,
                expected_page_count=preflight.page_count,
                pallet_blocks=pallet_blocks,
                extracted_tables=extracted_tables,
            )
        for issue in coverage_issues:
            (errors if issue.severity == "error" else warnings).append(issue)

        if template_id == BIGC_TEMPLATE_ID:
            for i, (raw, table) in enumerate(block_rows_for_reconcile, start=1):
                progress(f"คำนวณยอด {table.name}", i, len(block_rows_for_reconcile))
                for issue in reconcile_table(table, raw, settings):
                    (errors if issue.severity == "error" else warnings).append(issue)
        else:
            for i, (block, rows) in enumerate(block_rows_for_reconcile, start=1):
                progress(f"คำนวณยอด pallet {block.pallet_no}", i, len(block_rows_for_reconcile))
                for issue in reconcile_pallet_block(rows, block, settings):
                    (errors if issue.severity == "error" else warnings).append(issue)
        for table in extracted_tables:
            for issue in check_duplicate_rows(table):
                (errors if issue.severity == "error" else warnings).append(issue)
        reconciled = not errors
        validation = ValidationSummary(reconciled=reconciled, errors=errors, warnings=warnings)
        coverage_codes = [issue.code for issue in coverage_issues]
        log.record(
            "validation",
            f"reconciled={reconciled}; {len(errors)} errors, {len(warnings)} warnings; coverage={coverage_codes}",
        )

    with log.step("confidence_scoring", "composite document confidence + status"):
        confidence, status = score_document(extracted_tables, validation, settings)
        log.record("confidence_scoring", f"confidence={confidence:.2f}% status={status}")

    return DocumentResult(
        id=doc_id,
        filename=path.name,
        pages=preflight.page_count,
        document_type=template_id,
        engine_version=settings.engine_version,
        ocr_engine_version=ocr_engine_version,
        parser_version=settings.parser_version,
        template_version=template_version,
        confidence=confidence,
        status=status,
        tables=extracted_tables,
        fields=[],
        validation=validation,
        processing_log=log.entries,
        document_date=document_date.value if document_date else None,
        document_date_raw=document_date.raw_value if document_date else None,
        document_date_label=document_date.label if document_date else None,
        document_date_page=document_date.page if document_date else None,
    )
