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
import unicodedata
from dataclasses import dataclass, field

from pdf_document_intelligence.extract.text import PageText, Word
from pdf_document_intelligence.normalize.types import TypeParseError, parse_integer, parse_number
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
    # Set only when `text` was derived by splitting a glued word (see
    # split_glued_code_suffix) - holds the original, unsplit PDF text so
    # the evidence trail never loses what the source document actually
    # contained, even though `text` itself is now the corrected value.
    raw_text: str | None = None


def split_glued_code_suffix(text: str, code_re: re.Pattern[str]) -> tuple[str, str] | None:
    """Recovers two character streams the source PDF rendered at
    overlapping X positions and pdfplumber's word-clustering therefore
    merged into one "word" (observed: a department name overflowing its
    column, with an Article code's glyphs starting at almost the same X
    as the name's last couple of letters - see
    tests/integration/test_golden_regression_bpdc.py for the traced
    example). Never guesses at content: splits purely by character class
    (digit/hyphen vs. everything else), preserving each class's own
    relative left-to-right order, and returns a split only when the
    digit/hyphen stream is an exact match for `code_re` - otherwise
    returns None and the caller must leave the glued text untouched for a
    human to review, per this project's "never guess" rule.
    """
    code_chars = "".join(c for c in text if c.isdigit() or c == "-")
    label_chars = "".join(c for c in text if not (c.isdigit() or c == "-"))
    label = re.sub(r"\s+", " ", label_chars).strip()
    if not label or not code_re.match(code_chars):
        return None
    return label, code_chars


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


def _normalize_header_text(text: str) -> str:
    """Normalize harmless PDF text-layer differences in table headers.

    The two supported packing-list layouts are stable structurally, but
    different SAP/PDF exports can vary in case, punctuation and whether a
    multi-word label is emitted as one or several pdfplumber words. Those
    differences must not turn the same layout into UNKNOWN_LAYOUT.
    """
    value = unicodedata.normalize("NFKC", text).casefold()
    value = "".join(ch for ch in value if ch.isalnum())
    # The source exports use both Remark and REMARKS for the same optional
    # final column. Treat that spelling variation as equivalent only here;
    # no data-row values are normalized by this helper.
    if value == "remarks":
        return "remark"
    return value


def _match_header_phrase(
    row: list[Word], cursor: int, tokens: tuple[str, ...]
) -> tuple[int, float, float] | None:
    """Find one column label from ``cursor`` onward.

    Matching is ordered and geometry-preserving, but compares a normalized
    concatenation. This handles examples such as ``no`` vs ``no.``, case
    differences, and ``Order``+``no.`` being emitted as one PDF word,
    without weakening the actual column sequence required by a template.
    """
    target = "".join(_normalize_header_text(token) for token in tokens)
    if not target:
        return None

    for start in range(cursor, len(row)):
        combined = ""
        for end in range(start, len(row)):
            piece = _normalize_header_text(row[end].text)
            if not piece:
                continue
            combined += piece
            if combined == target:
                return end + 1, row[start].x0, row[end].x1
            if not target.startswith(combined):
                break
    return None


def find_header_boundaries(row: list[Word], columns: tuple[ColumnSpec, ...]) -> Boundaries | None:
    """Given one candidate header text-line (already clustered by top),
    matches `columns`' token sequences against it in order and returns
    per-column X boundaries, or None if the line doesn't match this
    template's full column set.

    Matching deliberately tolerates text-layer presentation differences
    (case, punctuation, merged/split words), but it still requires every
    template column in the original order. This keeps layout detection
    strict while avoiding false UNKNOWN_LAYOUT results for the same form.
    """
    row = sorted(row, key=lambda w: w.x0)
    matched: list[tuple[ColumnSpec, float, float]] = []
    cursor = 0
    for col in columns:
        found = _match_header_phrase(row, cursor, col.header_tokens)
        if found is None:
            return None
        cursor, found_x0, found_x1 = found
        matched.append((col, found_x0, found_x1))

    boundaries: Boundaries = {}
    for idx, (col, x0, x1) in enumerate(matched):
        left = 0.0 if idx == 0 else (matched[idx - 1][2] + x0) / 2
        right = (x1 + matched[idx + 1][1]) / 2 if idx + 1 < len(matched) else x1 + 500
        boundaries[col.canonical_name] = (left, right)
    return boundaries


def find_header_on_page(page: PageText, columns: tuple[ColumnSpec, ...]) -> tuple[float, Boundaries] | None:
    """Scans a whole page for the first line matching `columns`' header
    signature. Returns (header_bottom, boundaries) or None.

    We cluster candidate lines instead of anchoring on an exact ``DN``
    token so case/punctuation/word-grouping differences receive the same
    tolerant matching as ``find_header_boundaries``.
    """
    if not page.words:
        return None
    top_min = min(w.top for w in page.words) - 1.0
    top_max = max(w.bottom for w in page.words) + 1.0
    for row in cluster_rows(page.words, top_min, top_max):
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

    # Same locale-aware parsing (thousands separators, Thai digits) as every
    # row value goes through - a bare float()/int() here would raise on a
    # department total >= 1,000 (e.g. "1,267.30"), taking down the whole
    # document's processing instead of just leaving this one total
    # unreconciled (reconcile_table already handles a None total by
    # skipping that check, not by fabricating a match).
    def parse_decimal_or_none(text: str | None) -> float | None:
        if not text:
            return None
        try:
            return parse_number(text)
        except TypeParseError:
            return None

    def parse_int_or_none(text: str | None) -> int | None:
        if not text:
            return None
        try:
            return parse_integer(text)
        except TypeParseError:
            return None

    weight = in_col("weight_qty")
    pu = in_col("pu_qty")
    sku = in_col("sku_qty")
    return ParsedTotal(
        line_count=line_count,
        weight_qty=parse_decimal_or_none(weight),
        pu_qty=parse_int_or_none(pu),
        sku_qty=parse_int_or_none(sku),
        page=page_no,
    )
