"""Synthetic packing-list fixtures used by integration tests.

These PDFs are generated at test runtime from invented values only. No user,
company, shipment, product-master, or source-document data is stored here.
"""
from __future__ import annotations

from pathlib import Path

import fitz


PAGE = (0, 0, 1100, 620)
FONT_SIZE = 8
COL_STEP = 78
START_X = 35


def _put(page, x: float, y: float, text: str, size: float = FONT_SIZE) -> None:
    page.insert_text((x, y), text, fontsize=size, fontname="helv")


def _header(page, y: float, columns: list[tuple[str, ...]]) -> dict[int, float]:
    anchors: dict[int, float] = {}
    for i, tokens in enumerate(columns):
        x = START_X + i * COL_STEP
        anchors[i] = x
        for j, token in enumerate(tokens):
            _put(page, x + j * 24, y, token)
    return anchors


def make_bigc_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=PAGE[2], height=PAGE[3])
    _put(page, START_X, 80, "Packing List - SYNTHETIC TEST")
    _put(page, START_X, 120, "Department")
    _put(page, START_X + 70, 120, ":")
    _put(page, START_X + 85, 120, "SYNTHETIC")

    columns = [
        ("DN", "no"), ("DO",), ("Order", "no."), ("Line",),
        ("Pallet",), ("Lot",), ("Article",), ("Barcode",), ("Name",),
        ("Weight", "qty"), ("PU", "qty"), ("SKU", "qty"), ("REMARKS",),
    ]
    a = _header(page, 160, columns)
    row = [
        "100001", "200001", "300001", "10", "PAL-A", "LOT-A",
        "1234567-89-012", "9990000000001", "SYNTHETIC_ITEM",
        "1.5", "2", "3", "TEST",
    ]
    for i, value in enumerate(row):
        _put(page, a[i] + 2, 190, value)

    _put(page, START_X, 225, "Total")
    _put(page, a[3] + 2, 225, "1")
    _put(page, a[9] + 2, 225, "1.5")
    _put(page, a[10] + 2, 225, "2")
    _put(page, a[11] + 2, 225, "3")

    doc.save(path)
    doc.close()
    return path


def make_bpdc_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=PAGE[2], height=PAGE[3])
    _put(page, START_X, 80, "Packing List - SYNTHETIC BPDC TEST")

    _put(page, START_X, 150, "Pallet")
    _put(page, START_X + 42, 150, "no.")
    _put(page, START_X + 63, 150, ":")
    _put(page, START_X + 76, 150, "SYN-P01")
    _put(page, START_X + 155, 150, "Lot")
    _put(page, START_X + 180, 150, "no.")
    _put(page, START_X + 202, 150, ":")
    _put(page, START_X + 215, 150, "LOT-S01")

    columns = [
        ("DN", "no"), ("DO",), ("Order", "no."), ("Line",),
        ("Department",), ("Article",), ("Barcode",), ("Name",),
        ("Weight",), ("PU", "qty"), ("SKU", "qty"), ("Remark",),
    ]
    a = _header(page, 180, columns)
    row = [
        "110001", "220001", "330001", "20", "SYNTHETIC",
        "7654321-98-210", "9990000000002", "SYNTHETIC_BPDC_ITEM",
        "2.5", "4", "5", "TEST",
    ]
    for i, value in enumerate(row):
        _put(page, a[i] + 2, 210, value)

    _put(page, START_X, 245, "Total")
    _put(page, a[3] + 2, 245, "1")
    _put(page, a[8] + 2, 245, "2.5")
    _put(page, a[9] + 2, 245, "4")
    _put(page, a[10] + 2, 245, "5")

    doc.save(path)
    doc.close()
    return path
