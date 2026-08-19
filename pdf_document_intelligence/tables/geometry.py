"""Shared geometry primitives for table reconstruction, used by every
template's reconstruction module (proposal §13: geometry-driven, not
whitespace-driven). Column membership is decided from X position against
boundaries derived from a header row's own word positions (midpoints
between adjacent labels, not raw label x0 — narrow numeric columns bleed
into each other otherwise, see packing_list_bigc's original bug), with a
regex-assisted override for an article/barcode/name run that visually
overflows across column boundaries when Thai product-name text is long.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from pdf_document_intelligence.extract.text import PageText, Word
from pdf_document_intelligence.templates.base import ColumnSpec

ROW_TOLERANCE = 3.0
ARTICLE_RE = re.compile(r"^\d{6,9}-\d{2}-\d{3}$")
# Barcode values mix EAN-13 (8-14 digits) with shorter internal/produce
# codes (observed as few as 6-7 digits) across both known templates.
BARCODE_RE = re.compile(r"^\d{6,14}$")


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


Boundaries = dict[str, tuple[float, float]]


def cluster_rows(words: list[Word], top_min: float, top_max: float) -> list[list[Word]]:
    band = sorted((w for w in words if top_min <= w.top < top_max), key=lambda w: (w.top, w.x0))
    rows: list[list[Word]] = []
    current: list[Word] = []
    current_top: float | None = None
    for w in band:
        if current_top is None or w.top - current_top > ROW_TOLERANCE:
            if current:
                rows.append(current)
            current = [w]
            current_top = w.top
        else:
            current.append(w)
    if current:
        rows.append(current)
    return rows


def find_header_boundaries(row: list[Word], columns: tuple[ColumnSpec, ...]) -> Boundaries | None:
    """Given one candidate header text-line (already clustered by top),
    matches `columns`' token sequences against it in order and returns
    per-column X boundaries, or None if the line doesn't match this
    template's full column set."""
    row = sorted(row, key=lambda w: w.x0)
    matched: list[tuple[ColumnSpec, float, float]] = []
    cursor = 0
    for col in columns:
        found_x0 = found_x1 = None
        i = cursor
        for token in col.header_tokens:
            j = i
            while j < len(row) and row[j].text != token:
                j += 1
            if j >= len(row):
                return None
            if found_x0 is None:
                found_x0 = row[j].x0
            found_x1 = row[j].x1
            i = j + 1
        matched.append((col, found_x0, found_x1))
        cursor = i
    if len(matched) != len(columns):
        return None

    boundaries: Boundaries = {}
    for idx, (col, x0, x1) in enumerate(matched):
        left = 0.0 if idx == 0 else (matched[idx - 1][2] + x0) / 2
        right = (x1 + matched[idx + 1][1]) / 2 if idx + 1 < len(matched) else x1 + 500
        boundaries[col.canonical_name] = (left, right)
    return boundaries


def find_header_on_page(page: PageText, columns: tuple[ColumnSpec, ...]) -> tuple[float, Boundaries] | None:
    """Scans a whole page for the first line matching `columns`' header
    signature. Returns (header_bottom, boundaries) or None."""
    words = sorted(page.words, key=lambda w: (w.top, w.x0))
    first_token = columns[0].header_tokens[0]
    for anchor in words:
        if anchor.text != first_token:
            continue
        row = [w for w in words if abs(w.top - anchor.top) < 1.5]
        boundaries = find_header_boundaries(row, columns)
        if boundaries is not None:
            return max(w.bottom for w in row), boundaries
    return None


def assign_row(
    words: list[Word],
    page_no: int,
    top: float,
    boundaries: Boundaries,
    *,
    plain_columns: tuple[str, ...],
    article_col: str = "article",
    barcode_col: str = "barcode",
    name_col: str = "name",
) -> RawRow:
    """Assigns a row's words to columns by X-boundary, with a
    regex-assisted special case for the article/barcode/name span (see
    module docstring)."""
    remaining = list(words)
    cells: dict[str, Cell] = {}

    def take_by_boundary(col_name: str) -> list[Word]:
        left, right = boundaries[col_name]
        matched = [w for w in remaining if left <= w.x0 < right]
        for w in matched:
            remaining.remove(w)
        return matched

    for col_name in plain_columns:
        matched = take_by_boundary(col_name)
        matched.sort(key=lambda w: w.x0)
        cells[col_name] = Cell(text=" ".join(w.text for w in matched), words=matched)

    article_left, _ = boundaries[article_col]
    _, name_right = boundaries[name_col]
    span = [w for w in remaining if article_left <= w.x0 < name_right]
    article_words = [w for w in span if ARTICLE_RE.match(w.text)]
    barcode_words = [w for w in span if BARCODE_RE.match(w.text)]
    consumed = set(id(w) for w in article_words + barcode_words)
    name_words = sorted([w for w in span if id(w) not in consumed], key=lambda w: w.x0)
    for w in article_words + barcode_words + name_words:
        if w in remaining:
            remaining.remove(w)

    cells[article_col] = Cell(text=" ".join(w.text for w in article_words), words=article_words)
    cells[barcode_col] = Cell(text=" ".join(w.text for w in barcode_words), words=barcode_words)
    cells[name_col] = Cell(text=" ".join(w.text for w in name_words), words=name_words)

    return RawRow(page=page_no, top=top, cells=cells)


def find_total_row(words: list[Word], total_label: str) -> list[Word] | None:
    words = sorted(words, key=lambda w: (w.top, w.x0))
    for w in words:
        if w.text == total_label:
            return [x for x in words if abs(x.top - w.top) < 1.5]
    return None


@dataclass
class ParsedTotal:
    line_count: int | None
    weight_qty: float | None
    pu_qty: int | None
    sku_qty: int | None
    page: int


def parse_total(
    total_words: list[Word], page_no: int, boundaries: Boundaries, total_label: str
) -> ParsedTotal:
    total_words = sorted(total_words, key=lambda w: w.x0)
    label_idx = next(i for i, w in enumerate(total_words) if w.text == total_label)
    line_count = None
    for w in total_words[label_idx + 1 :]:
        if w.text.isdigit():
            line_count = int(w.text)
            break

    def in_col(col_name: str) -> str | None:
        left, right = boundaries[col_name]
        matched = [w.text for w in total_words if left <= w.x0 < right]
        return matched[0] if matched else None

    weight = in_col("weight_qty")
    pu = in_col("pu_qty")
    sku = in_col("sku_qty")
    return ParsedTotal(
        line_count=line_count,
        weight_qty=float(weight) if weight else None,
        pu_qty=int(pu) if pu else None,
        sku_qty=int(sku) if sku else None,
        page=page_no,
    )
