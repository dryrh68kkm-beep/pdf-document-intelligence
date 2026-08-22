"""Evidence-based document coverage checks.

These checks close a reliability gap between successful parsing and complete
parsing. A document must not be auto-approved merely because some rows were
reconstructed: page extraction count, data-bearing pages, and reconstructed
blocks/tables must all be internally consistent.

The validator is intentionally conservative. It never invents expected row
counts. It only raises an error when the source itself provides concrete
evidence that data should have been reconstructed (for example an Article
code on a page) but no parsed row from that page exists.
"""
from __future__ import annotations

from typing import Iterable

from pdf_document_intelligence.extract.text import DocumentText
from pdf_document_intelligence.models.document import ExtractedTable, ValidationIssue
from pdf_document_intelligence.tables.geometry import ARTICLE_RE, find_header_on_page
from pdf_document_intelligence.tables.reconstruct import RawTable
from pdf_document_intelligence.tables.reconstruct_bpdc import PalletBlock
from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS as BIGC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bigc import DEPARTMENT_LABEL


def _row_pages(tables: Iterable[ExtractedTable]) -> set[int]:
    pages: set[int] = set()
    for table in tables:
        for row in table.rows:
            for field in row.fields.values():
                pages.add(field.bbox.page)
    return pages


def _base_coverage_issues(
    doc_text: DocumentText,
    expected_page_count: int,
    extracted_tables: list[ExtractedTable],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    extracted_page_numbers = [page.page_number for page in doc_text.pages]
    expected_page_numbers = list(range(1, expected_page_count + 1))

    if extracted_page_numbers != expected_page_numbers:
        missing = sorted(set(expected_page_numbers) - set(extracted_page_numbers))
        extra = sorted(set(extracted_page_numbers) - set(expected_page_numbers))
        issues.append(
            ValidationIssue(
                code="PAGE_COUNT_MISMATCH",
                message=(
                    f"PDF preflight reports {expected_page_count} pages but text extraction returned "
                    f"{len(extracted_page_numbers)} pages; missing={missing}, extra={extra}"
                ),
                severity="error",
            )
        )

    total_rows = sum(len(table.rows) for table in extracted_tables)
    if total_rows == 0:
        issues.append(
            ValidationIssue(
                code="ZERO_PRODUCT_ROWS",
                message="Supported document template was detected but zero product rows were reconstructed",
                severity="error",
            )
        )

    return issues


def _article_pages(doc_text: DocumentText) -> set[int]:
    """Pages with source-level evidence of product rows.

    Article codes have a strict format (e.g. 1234567-89-012), so this is a
    stronger signal than generic numeric/barcode-looking text and avoids
    guessing whether cover/summary pages should contain table rows.
    """
    return {
        page.page_number
        for page in doc_text.pages
        if any(ARTICLE_RE.fullmatch(word.text.strip()) for word in page.words)
    }


def validate_bigc_coverage(
    doc_text: DocumentText,
    expected_page_count: int,
    raw_tables: list[RawTable],
    extracted_tables: list[ExtractedTable],
) -> list[ValidationIssue]:
    issues = _base_coverage_issues(doc_text, expected_page_count, extracted_tables)
    parsed_pages = _row_pages(extracted_tables)

    for page_no in sorted(_article_pages(doc_text) - parsed_pages):
        issues.append(
            ValidationIssue(
                code="PAGE_DATA_MISSING",
                message=f"Page {page_no} contains Article-code evidence but produced no parsed product row",
                severity="error",
            )
        )

    for page in doc_text.pages:
        has_department_label = any(word.text == DEPARTMENT_LABEL for word in page.words)
        if has_department_label and find_header_on_page(page, BIGC_COLUMNS) is None:
            issues.append(
                ValidationIssue(
                    code="TABLE_HEADER_MISSING",
                    message=f"Page {page.page_number} contains a Department label but the expected Big C table header was not found",
                    severity="error",
                )
            )

    for raw in raw_tables:
        if not raw.rows:
            issues.append(
                ValidationIssue(
                    code="EMPTY_TABLE",
                    message=(
                        f"Department {raw.department!r} was detected on pages {raw.page_start}-{raw.page_end} "
                        "but no product rows were reconstructed"
                    ),
                    severity="error",
                    table=raw.department,
                )
            )

    return issues


def validate_bpdc_coverage(
    doc_text: DocumentText,
    expected_page_count: int,
    pallet_blocks: list[PalletBlock],
    extracted_tables: list[ExtractedTable],
) -> list[ValidationIssue]:
    issues = _base_coverage_issues(doc_text, expected_page_count, extracted_tables)
    parsed_pages = _row_pages(extracted_tables)

    for page_no in sorted(_article_pages(doc_text) - parsed_pages):
        issues.append(
            ValidationIssue(
                code="PAGE_DATA_MISSING",
                message=f"Page {page_no} contains Article-code evidence but produced no parsed product row",
                severity="error",
            )
        )

    for block in pallet_blocks:
        if not block.rows:
            issues.append(
                ValidationIssue(
                    code="EMPTY_PALLET_BLOCK",
                    message=(
                        f"Pallet {block.pallet_no or '<missing>'!r} was detected on pages "
                        f"{block.page_start}-{block.page_end} but no product rows were reconstructed"
                    ),
                    severity="error",
                    table=block.pallet_no or None,
                )
            )
        if not block.pallet_no:
            issues.append(
                ValidationIssue(
                    code="PALLET_ID_MISSING",
                    message=f"A pallet block beginning on page {block.page_start} has no parsed pallet identifier",
                    severity="warning",
                )
            )

    return issues


__all__ = ["validate_bigc_coverage", "validate_bpdc_coverage"]
