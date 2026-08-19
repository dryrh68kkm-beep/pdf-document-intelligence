"""TableDetector + TableReconstructor for the packing_list_bpdc template.

Unlike packing_list_bigc (one header per page, one Department per page),
this template repeats a full "Pallet no. / Lot no." + column-header pair
per block, with potentially several blocks per page — and a block's rows
can continue onto the next page *without* repeating either line (observed
directly in the sample: page 3 ends right after a block's header with no
data rows yet, page 4 opens straight into that block's data). So this
reconstructs across the whole document as one ordered stream of markers
(pallet-line / header-line / total-line / data-row) rather than per-page,
carrying the last-known column boundaries and open block across a page
boundary when a continuation page has neither.

Department is an inline, forward-filled column here (see templates/
packing_list_bpdc.py) — it can change mid-block, unlike dn_no/do_no/
order_no which only forward-fill within one DN's own continuation lines.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pdf_document_intelligence.extract.text import DocumentText, Word
from pdf_document_intelligence.tables.geometry import (
    ARTICLE_RE,
    Boundaries,
    Cell,
    ParsedTotal,
    RawRow,
    TableStructureError,
    assign_row,
    cluster_rows,
    find_header_boundaries,
    parse_total,
    split_glued_code_suffix,
)
from pdf_document_intelligence.templates.packing_list_bpdc import (
    COLUMNS,
    LOT_LABEL,
    PALLET_LABEL,
    TOTAL_LABEL,
)

_PLAIN_COLUMNS = ("dn_no", "do_no", "order_no", "line", "department", "weight_qty", "pu_qty", "sku_qty", "remarks")
# Everything above this Y position on every page is fixed page boilerplate
# (Consignee/address block, "Packing List" title, Route/Transport Note) -
# verified against the sample: boilerplate's last line sits at top≈129,
# every marker/data row starts at top≈142.9 or later, on every page
# including continuation pages that repeat the same boilerplate at top.
_CONTENT_TOP_MIN = 135.0


@dataclass
class PalletBlock:
    pallet_no: str
    lot_no: str | None
    page_start: int
    page_end: int
    rows: list[RawRow] = field(default_factory=list)
    total: ParsedTotal | None = None


def _line_kind(row: list[Word]) -> str:
    row = sorted(row, key=lambda w: w.x0)
    texts = [w.text for w in row]
    if texts[:1] == [PALLET_LABEL]:
        return "pallet"
    if len(texts) >= 2 and texts[0] == COLUMNS[0].header_tokens[0] and texts[1] == COLUMNS[0].header_tokens[1]:
        return "header"
    if TOTAL_LABEL in texts:
        return "total"
    return "data"


def _parse_pallet_line(row: list[Word]) -> tuple[str, str | None]:
    row = sorted(row, key=lambda w: w.x0)
    lot_idx = next((i for i, w in enumerate(row) if w.text == LOT_LABEL), None)
    # Pallet id: the value between "Pallet no. :" and the "Lot" label (or
    # end of line if no Lot label found).
    pallet_words = [w for w in row if w.x0 > 71 and (lot_idx is None or w.x0 < row[lot_idx].x0)]
    pallet_id = "".join(w.text for w in pallet_words).strip()
    lot_no = None
    if lot_idx is not None:
        lot_words = [w for w in row[lot_idx:] if w.text not in (LOT_LABEL, "no.", ":")]
        lot_no = " ".join(w.text for w in lot_words).strip() or None
    return pallet_id, lot_no


def _split_department_article_overflow(raw_row: RawRow) -> None:
    """When "Department" is long enough to overflow its printed column
    width, its glyphs can visually overlap the Article code's - observed
    directly in the sample (e.g. "STATIONERY & EDUTAINMEN1T02313106-00-001")
    and traced at the character level: it's two separate text runs at
    near-identical X positions, not a single mangled word. Only applies
    when the article cell for this row came out empty (i.e. its own words
    genuinely got swallowed into the department cell) - never overwrites a
    cleanly-extracted article."""
    dept_cell = raw_row.cells.get("department")
    article_cell = raw_row.cells.get("article")
    if not dept_cell or not dept_cell.text or article_cell is None or article_cell.text:
        return
    split = split_glued_code_suffix(dept_cell.text, ARTICLE_RE)
    if split is None:
        return
    label, code = split
    original = dept_cell.text
    raw_row.cells["department"] = Cell(text=label, words=dept_cell.words, raw_text=original)
    raw_row.cells["article"] = Cell(text=code, words=dept_cell.words, raw_text=original)


def reconstruct_tables(doc: DocumentText) -> list[PalletBlock]:
    blocks: list[PalletBlock] = []
    boundaries: Boundaries | None = None
    open_block: PalletBlock | None = None

    for page in doc.pages:
        content_words = [w for w in page.words if w.top >= _CONTENT_TOP_MIN]
        lines = cluster_rows(content_words, _CONTENT_TOP_MIN, 10_000.0)

        for row in lines:
            kind = _line_kind(row)

            if kind == "pallet":
                if open_block is not None:
                    # Malformed/unexpected: a new pallet line without a
                    # preceding Total for the previous block. Close it
                    # defensively rather than merge two pallets' rows.
                    blocks.append(open_block)
                pallet_id, lot_no = _parse_pallet_line(row)
                open_block = PalletBlock(pallet_no=pallet_id, lot_no=lot_no, page_start=page.page_number, page_end=page.page_number)
                continue

            if kind == "header":
                found = find_header_boundaries(row, COLUMNS)
                if found is not None:
                    boundaries = found
                continue

            if kind == "total":
                if open_block is not None and boundaries is not None:
                    open_block.total = parse_total(row, page.page_number, boundaries, TOTAL_LABEL)
                    open_block.page_end = page.page_number
                    blocks.append(open_block)
                open_block = None
                continue

            # data row
            if open_block is None or boundaries is None:
                continue  # stray content before the first block; ignore
            row_top = min(w.top for w in row)
            raw_row = assign_row(row, page.page_number, row_top, boundaries, plain_columns=_PLAIN_COLUMNS)
            _split_department_article_overflow(raw_row)
            open_block.rows.append(raw_row)
            open_block.page_end = page.page_number

    if open_block is not None:
        blocks.append(open_block)

    return blocks


__all__ = ["reconstruct_tables", "PalletBlock", "RawRow", "Cell", "TableStructureError"]
