"""Regression guard (L1-003): a department's printed Total line must
parse the same way any other numeric cell does (thousands separators,
Thai digits) - a bare float()/int() previously raised on a total >= 1,000
(e.g. "1,267.30"), crashing the whole document's processing instead of
leaving just that one total unreconciled.
"""
from __future__ import annotations

from pdf_document_intelligence.extract.text import Word
from pdf_document_intelligence.tables.geometry import parse_total

BOUNDARIES = {
    "weight_qty": (0.0, 100.0),
    "pu_qty": (100.0, 200.0),
    "sku_qty": (200.0, 300.0),
}


def _word(text, x0):
    return Word(text=text, x0=x0, top=0, x1=x0 + 5, bottom=10, page=1)


def test_parses_totals_with_thousands_separators():
    words = [
        _word("Total", -10),
        _word("1,267.30", 10),
        _word("848", 110),
        _word("1,771", 210),
    ]
    result = parse_total(words, page_no=1, boundaries=BOUNDARIES, total_label="Total")
    assert result.weight_qty == 1267.30
    assert result.pu_qty == 848
    assert result.sku_qty == 1771


def test_plain_totals_without_separators_still_work():
    words = [_word("Total", -10), _word("126", 10), _word("14", 110), _word("14", 210)]
    result = parse_total(words, page_no=1, boundaries=BOUNDARIES, total_label="Total")
    assert result.weight_qty == 126.0
    assert result.pu_qty == 14
    assert result.sku_qty == 14


def test_unparseable_total_cell_yields_none_not_a_crash():
    words = [_word("Total", -10), _word("N/A", 10)]
    result = parse_total(words, page_no=1, boundaries=BOUNDARIES, total_label="Total")
    assert result.weight_qty is None
