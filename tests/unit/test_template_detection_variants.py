from __future__ import annotations

from pdf_document_intelligence.extract.text import DocumentText, PageText, TextQuality, Word
from pdf_document_intelligence.tables.geometry import find_header_boundaries
from pdf_document_intelligence.tables.reconstruct_bpdc import _line_kind, _parse_pallet_line
from pdf_document_intelligence.templates.detect import detect_template
from pdf_document_intelligence.templates.packing_list_bpdc import COLUMNS as BPDC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bpdc import TEMPLATE_ID as BPDC_TEMPLATE_ID


def _quality() -> TextQuality:
    return TextQuality(
        printable_ratio=1.0,
        thai_valid_ratio=1.0,
        replacement_char_ratio=0.0,
        thai_combining_density=-1.0,
        score=1.0,
        reliable=True,
    )


def _words(texts: list[str], *, top: float = 150.0, page: int = 1) -> list[Word]:
    out: list[Word] = []
    x = 20.0
    for text in texts:
        width = max(18.0, len(text) * 5.0)
        out.append(Word(text=text, x0=x, top=top, x1=x + width, bottom=top + 10.0, page=page))
        x += width + 8.0
    return out


def _bpdc_variant_header(page: int = 1) -> list[Word]:
    return _words(
        [
            "dn",
            "NO.",
            "do",
            "Order no",
            "LINE",
            "department",
            "ARTICLE",
            "barcode",
            "Name",
            "weight",
            "pu",
            "QTY",
            "sku",
            "Qty.",
            "REMARKS",
        ],
        page=page,
    )


def test_bpdc_header_matching_tolerates_case_punctuation_and_word_grouping() -> None:
    boundaries = find_header_boundaries(_bpdc_variant_header(), BPDC_COLUMNS)
    assert boundaries is not None
    assert set(boundaries) == {col.canonical_name for col in BPDC_COLUMNS}


def test_template_detection_scans_past_first_three_pages() -> None:
    pages = [
        PageText(page_number=i, words=_words(["Packing", "List"], page=i), raw_text="Packing List", quality=_quality())
        for i in range(1, 4)
    ]
    pages.append(
        PageText(
            page_number=4,
            words=_bpdc_variant_header(page=4),
            raw_text="DN no DO Order no Line Department Article Barcode Name Weight PU qty SKU qty Remarks",
            quality=_quality(),
        )
    )

    assert detect_template(DocumentText(pages=pages)) == BPDC_TEMPLATE_ID


def test_bpdc_pallet_marker_accepts_merged_no_variant() -> None:
    row = _words(["Pallet no.", ":", "P123", "Lot no.", ":", "L456"])
    assert _line_kind(row) == "pallet"
    pallet, lot = _parse_pallet_line(row)
    assert pallet == "P123"
    assert lot == "L456"


def test_bpdc_total_marker_accepts_case_and_punctuation_variant() -> None:
    row = _words(["TOTAL:", "10", "100.00", "20", "30"])
    assert _line_kind(row) == "total"
