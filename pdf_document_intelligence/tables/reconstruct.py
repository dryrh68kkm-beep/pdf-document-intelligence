"""TableDetector + TableReconstructor for the packing_list_bigc template
(one Department heading per page/page-group; header appears once per
page). Geometry primitives are shared with other templates via
tables/geometry.py — see that module's docstring for the article/barcode/
name overflow handling rationale.

Multi-page stitching (§18): a department's table can span pages (e.g. the
BAKERY table's header+rows on page 1 continue into page 2's "Total" row).
We treat consecutive pages carrying the same Department value as one
logical table, closing it when a "Total" row is found.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

from pdf_document_intelligence.extract.text import DocumentText, PageText, Word
from pdf_document_intelligence.tables.geometry import (
    Boundaries,
    Cell,
    ParsedTotal,
    RawRow,
    TableStructureError,
    assign_row,
    cluster_rows,
    find_header_on_page,
    parse_total,
)
from pdf_document_intelligence.templates.packing_list_bigc import (
    COLUMNS,
    DEPARTMENT_LABEL,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    TOTAL_LABEL,
)

_PLAIN_COLUMNS = ("dn_no", "do_no", "order_no", "line", "pallet", "lot", "weight_qty", "pu_qty", "sku_qty", "remarks")

DepartmentTotal = ParsedTotal


@dataclass
class RawTable:
    department: str
    page_start: int
    page_end: int
    rows: list[RawRow] = field(default_factory=list)
    total: ParsedTotal | None = None


def _marker_text(text: str) -> str:
    """Normalize presentation-only differences for structural labels."""
    value = unicodedata.normalize("NFKC", text).casefold()
    return "".join(ch for ch in value if ch.isalnum())


def _find_department(page: PageText) -> str | None:
    words = sorted(page.words, key=lambda w: (w.top, w.x0))
    department_key = _marker_text(DEPARTMENT_LABEL)
    for w in words:
        marker = _marker_text(w.text)
        if marker == department_key or marker.startswith(department_key):
            line = [x for x in words if abs(x.top - w.top) < 1.5 and x.x0 > w.x0]
            line.sort(key=lambda x: x.x0)
            value_words = [x.text for x in line if _marker_text(x.text)]
            return " ".join(value_words).strip() or None
    return None


def _find_total_row(page: PageText) -> list[Word] | None:
    """Find Total despite harmless case/punctuation differences.

    ``parse_total`` deliberately expects the canonical literal label, so the
    matching marker word is replaced only in this temporary row copy while
    retaining its original geometry. No product data is normalized here.
    """
    total_key = _marker_text(TOTAL_LABEL)
    words = sorted(page.words, key=lambda w: (w.top, w.x0))
    for w in words:
        marker = _marker_text(w.text)
        if marker == total_key or marker.startswith(total_key):
            row = [x for x in words if abs(x.top - w.top) < 1.5]
            normalized: list[Word] = []
            replaced = False
            for x in row:
                x_marker = _marker_text(x.text)
                if not replaced and (x_marker == total_key or x_marker.startswith(total_key)):
                    normalized.append(
                        Word(
                            text=TOTAL_LABEL,
                            x0=x.x0,
                            top=x.top,
                            x1=x.x1,
                            bottom=x.bottom,
                            page=x.page,
                        )
                    )
                    replaced = True
                else:
                    normalized.append(x)
            return normalized
    return None


def reconstruct_tables(doc: DocumentText) -> list[RawTable]:
    tables: list[RawTable] = []
    current: RawTable | None = None

    for page in doc.pages:
        header = find_header_on_page(page, COLUMNS)
        if header is None:
            continue  # coverage validation records supported pages that unexpectedly lose their header
        header_bottom, boundaries = header
        department = _find_department(page) or (current.department if current else "UNKNOWN")

        if current is None or current.department != department:
            if current is not None:
                tables.append(current)
            current = RawTable(department=department, page_start=page.page_number, page_end=page.page_number)
        current.page_end = page.page_number

        total_row_words = _find_total_row(page)
        top_max = min(w.top for w in total_row_words) if total_row_words else 10_000.0

        row_word_groups = cluster_rows(page.words, header_bottom + 1, top_max - 1)
        for group in row_word_groups:
            row_top = min(w.top for w in group)
            current.rows.append(
                assign_row(group, page.page_number, row_top, boundaries, plain_columns=_PLAIN_COLUMNS)
            )

        if total_row_words:
            current.total = parse_total(total_row_words, page.page_number, boundaries, TOTAL_LABEL)
            tables.append(current)
            current = None

    if current is not None:
        tables.append(current)

    return tables


__all__ = ["reconstruct_tables", "RawTable", "RawRow", "Cell", "DepartmentTotal", "TableStructureError", "TEMPLATE_ID", "TEMPLATE_VERSION"]
