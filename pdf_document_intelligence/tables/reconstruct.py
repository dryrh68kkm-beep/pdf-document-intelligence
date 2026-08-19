"""TableDetector + TableReconstructor for the packing-list template.

Geometry-driven, not whitespace-driven (proposal §13): column membership
is decided from X position against boundaries derived from the header
row's own word positions, with a regex-based override for the
article/barcode/name run — because on this real sample, Thai product-name
text (already flagged low-quality by TextExtractor, see extract/text.py)
visually overflows left into the barcode column's X range whenever the
name is long. Rather than mis-assign that overflow to "barcode", we
identify barcode/article by pattern and bucket everything else in that
span as the name — genuinely geometric, just pattern-assisted where two
columns share physical space.

Multi-page stitching (§18): a department's table can span pages (e.g. the
BAKERY table's header+rows on page 1 continue into page 2's "Total" row).
We treat consecutive pages carrying the same Department value as one
logical table, closing it when a "Total" row is found.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pdf_document_intelligence.extract.text import DocumentText, PageText, Word
from pdf_document_intelligence.templates.packing_list_bigc import (
    COLUMNS,
    DEPARTMENT_LABEL,
    TEMPLATE_ID,
    TEMPLATE_VERSION,
    TOTAL_LABEL,
    ColumnSpec,
)

_ROW_TOLERANCE = 3.0
_ARTICLE_RE = re.compile(r"^\d{6,9}-\d{2}-\d{3}$")
# Barcode values in this document mix EAN-13 (8-14 digits) with shorter
# internal/produce codes (observed as few as 7 digits, e.g. "0211125") —
# widened from an initial 8-14 assumption after that undershoot was caught
# against the golden sample.
_BARCODE_RE = re.compile(r"^\d{6,14}$")


class TableStructureError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class Cell:
    text: str
    words: list[Word]


@dataclass
class RawRow:
    page: int
    top: float
    cells: dict[str, Cell]


@dataclass
class DepartmentTotal:
    line_count: int | None
    weight_qty: float | None
    pu_qty: int | None
    sku_qty: int | None
    page: int


@dataclass
class RawTable:
    department: str
    page_start: int
    page_end: int
    rows: list[RawRow] = field(default_factory=list)
    total: DepartmentTotal | None = None


def _cluster_rows(words: list[Word], top_min: float, top_max: float) -> list[list[Word]]:
    band = sorted((w for w in words if top_min <= w.top < top_max), key=lambda w: (w.top, w.x0))
    rows: list[list[Word]] = []
    current: list[Word] = []
    current_top: float | None = None
    for w in band:
        if current_top is None or w.top - current_top > _ROW_TOLERANCE:
            if current:
                rows.append(current)
            current = [w]
            current_top = w.top
        else:
            current.append(w)
    if current:
        rows.append(current)
    return rows


def _find_header(page: PageText) -> tuple[float, dict[str, tuple[float, float]]] | None:
    """Returns (header_bottom, {canonical_name: (x_left, x_right)}) or None
    if this page doesn't carry the column header row."""
    words = sorted(page.words, key=lambda w: (w.top, w.x0))
    for anchor in words:
        if anchor.text != COLUMNS[0].header_tokens[0]:
            continue
        row = [w for w in words if abs(w.top - anchor.top) < 1.5]
        row.sort(key=lambda w: w.x0)
        matched: list[tuple[ColumnSpec, float, float]] = []
        cursor = 0
        ok = True
        for col in COLUMNS:
            found_x0 = found_x1 = None
            i = cursor
            for token in col.header_tokens:
                # search forward from cursor for this token
                j = i
                while j < len(row) and row[j].text != token:
                    j += 1
                if j >= len(row):
                    ok = False
                    break
                if found_x0 is None:
                    found_x0 = row[j].x0
                found_x1 = row[j].x1
                i = j + 1
            if not ok:
                break
            matched.append((col, found_x0, found_x1))
            cursor = i
        if not ok or len(matched) != len(COLUMNS):
            continue
        # Boundaries are midpoints between adjacent header labels, not raw
        # header x0s: numeric data (e.g. a DO number, a Lot code) commonly
        # starts a few points left of its own header label, so a boundary
        # anchored directly on the next header's x0 mis-captures it into the
        # previous column (observed: DN/DO and Pallet/Lot bleed on this
        # sample without the midpoint buffer).
        boundaries: dict[str, tuple[float, float]] = {}
        for idx, (col, x0, x1) in enumerate(matched):
            left = 0.0 if idx == 0 else (matched[idx - 1][2] + x0) / 2
            right = (x1 + matched[idx + 1][1]) / 2 if idx + 1 < len(matched) else x1 + 500
            boundaries[col.canonical_name] = (left, right)
        header_bottom = max(w.bottom for w in row)
        return header_bottom, boundaries
    return None


def _find_department(page: PageText) -> str | None:
    words = sorted(page.words, key=lambda w: (w.top, w.x0))
    for i, w in enumerate(words):
        if w.text == DEPARTMENT_LABEL:
            line = [x for x in words if abs(x.top - w.top) < 1.5 and x.x0 > w.x0]
            line.sort(key=lambda x: x.x0)
            value_words = [x.text for x in line if x.text != ":"]
            return " ".join(value_words).strip() or None
    return None


def _find_total_row(page: PageText) -> list[Word] | None:
    words = sorted(page.words, key=lambda w: (w.top, w.x0))
    for w in words:
        if w.text == TOTAL_LABEL:
            return [x for x in words if abs(x.top - w.top) < 1.5]
    return None


def _assign_row(words: list[Word], page_no: int, top: float, boundaries: dict[str, tuple[float, float]]) -> RawRow:
    remaining = list(words)
    cells: dict[str, Cell] = {}

    def take_by_boundary(name: str) -> list[Word]:
        left, right = boundaries[name]
        matched = [w for w in remaining if left <= w.x0 < right]
        for w in matched:
            remaining.remove(w)
        return matched

    for name in ("dn_no", "do_no", "order_no", "line", "pallet", "lot"):
        matched = take_by_boundary(name)
        matched.sort(key=lambda w: w.x0)
        cells[name] = Cell(text=" ".join(w.text for w in matched), words=matched)

    # article/barcode/name share a visually contested span: pick article and
    # barcode by pattern, treat every leftover word in that span as name.
    article_left, _ = boundaries["article"]
    name_left, name_right = boundaries["name"]
    span = [w for w in remaining if article_left <= w.x0 < name_right]
    article_words = [w for w in span if _ARTICLE_RE.match(w.text)]
    barcode_words = [w for w in span if _BARCODE_RE.match(w.text)]
    consumed = set(id(w) for w in article_words + barcode_words)
    name_words = sorted([w for w in span if id(w) not in consumed], key=lambda w: w.x0)
    for w in article_words + barcode_words + name_words:
        if w in remaining:
            remaining.remove(w)

    cells["article"] = Cell(text=" ".join(w.text for w in article_words), words=article_words)
    cells["barcode"] = Cell(text=" ".join(w.text for w in barcode_words), words=barcode_words)
    cells["name"] = Cell(text=" ".join(w.text for w in name_words), words=name_words)

    for name in ("weight_qty", "pu_qty", "sku_qty", "remarks"):
        matched = take_by_boundary(name)
        matched.sort(key=lambda w: w.x0)
        cells[name] = Cell(text=" ".join(w.text for w in matched), words=matched)

    return RawRow(page=page_no, top=top, cells=cells)


def _parse_total(total_words: list[Word], page_no: int, boundaries: dict[str, tuple[float, float]]) -> DepartmentTotal:
    total_words = sorted(total_words, key=lambda w: w.x0)
    label_idx = next(i for i, w in enumerate(total_words) if w.text == TOTAL_LABEL)
    line_count = None
    for w in total_words[label_idx + 1 :]:
        if w.text.isdigit():
            line_count = int(w.text)
            break

    def in_col(name: str) -> str | None:
        left, right = boundaries[name]
        matched = [w.text for w in total_words if left <= w.x0 < right]
        return matched[0] if matched else None

    weight = in_col("weight_qty")
    pu = in_col("pu_qty")
    sku = in_col("sku_qty")
    return DepartmentTotal(
        line_count=line_count,
        weight_qty=float(weight) if weight else None,
        pu_qty=int(pu) if pu else None,
        sku_qty=int(sku) if sku else None,
        page=page_no,
    )


def reconstruct_tables(doc: DocumentText) -> list[RawTable]:
    tables: list[RawTable] = []
    current: RawTable | None = None

    for page in doc.pages:
        header = _find_header(page)
        if header is None:
            continue  # page carries no data table (shouldn't happen for this template)
        header_bottom, boundaries = header
        department = _find_department(page) or (current.department if current else "UNKNOWN")

        if current is None or current.department != department:
            if current is not None:
                tables.append(current)
            current = RawTable(department=department, page_start=page.page_number, page_end=page.page_number)
        current.page_end = page.page_number

        total_row_words = _find_total_row(page)
        top_max = min(w.top for w in total_row_words) if total_row_words else 10_000.0

        row_word_groups = _cluster_rows(page.words, header_bottom + 1, top_max - 1)
        for group in row_word_groups:
            row_top = min(w.top for w in group)
            current.rows.append(_assign_row(group, page.page_number, row_top, boundaries))

        if total_row_words:
            current.total = _parse_total(total_row_words, page.page_number, boundaries)
            tables.append(current)
            current = None

    if current is not None:
        tables.append(current)

    return tables


__all__ = ["reconstruct_tables", "RawTable", "RawRow", "Cell", "DepartmentTotal", "TableStructureError", "TEMPLATE_ID", "TEMPLATE_VERSION"]
