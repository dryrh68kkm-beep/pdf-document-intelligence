"""Runtime-generated PDF fixtures containing no production/company data.

The files are created only inside pytest temporary directories and are never
committed. Values are intentionally fictional while preserving the two table
layouts that the parser must support.
"""
from __future__ import annotations

from pathlib import Path

import fitz


def _write_row(page, y: float, xs: list[float], values: list[str], size: float = 8) -> None:
    for x, value in zip(xs, values):
        if value:
            page.insert_text((x, y), value, fontsize=size)


def make_bigc_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=1600, height=500)
    xs = [20, 105, 170, 270, 330, 395, 455, 580, 700, 1020, 1120, 1210, 1300]
    headers = [
        "DN no", "DO", "Order no.", "Line", "Pallet", "Lot", "Article",
        "Barcode", "Name", "Weight qty", "PU qty", "SKU qty", "REMARKS",
    ]
    page.insert_text((20, 55), "Packing List", fontsize=11)
    page.insert_text((20, 75), "Consignee : SYNTHETIC STORE", fontsize=8)
    page.insert_text((20, 95), "Route : TEST-ROUTE", fontsize=8)
    page.insert_text((20, 120), "Department : SYNTHETIC FOOD", fontsize=8)
    page.insert_text((900, 75), "Document Date : 15/08/2026", fontsize=8)
    _write_row(page, 150, xs, headers)
    _write_row(
        page,
        185,
        xs,
        [
            "100001", "200001", "300001", "1", "P001", "L001",
            "12345678-00-001", "9990000000001", "Synthetic Product A",
            "10.00", "2", "4", "",
        ],
    )
    # Real layouts declare the number of detail rows immediately after Total.
    page.insert_text((900, 220), "Total", fontsize=8)
    page.insert_text((980, 220), "1", fontsize=8)
    _write_row(page, 220, xs, ["", "", "", "", "", "", "", "", "", "10.00", "2", "4", ""])
    doc.save(path)
    doc.close()
    return path


def make_bpdc_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page(width=1600, height=550)
    xs = [20, 105, 170, 270, 330, 500, 625, 745, 1060, 1160, 1250, 1340]
    headers = [
        "DN no", "DO", "Order no.", "Line", "Department", "Article",
        "Barcode", "Name", "Weight", "PU qty", "SKU qty", "Remark",
    ]
    page.insert_text((20, 55), "Packing List", fontsize=11)
    page.insert_text((20, 75), "Consignee : SYNTHETIC STORE", fontsize=8)
    page.insert_text((20, 95), "Route : TEST-ROUTE", fontsize=8)
    page.insert_text((900, 95), "Document Date : 16/08/2026", fontsize=8)
    page.insert_text((20, 155), "Pallet no. : SYN001 Lot no. : LOT001", fontsize=8)
    _write_row(page, 185, xs, headers)
    _write_row(
        page,
        220,
        xs,
        [
            "110001", "210001", "310001", "1", "SYNTHETIC BEVERAGE",
            "87654321-00-001", "9990000000002", "Synthetic Product B",
            "12.50", "3", "6", "FOC",
        ],
    )
    page.insert_text((960, 255), "Total", fontsize=8)
    page.insert_text((1020, 255), "1", fontsize=8)
    _write_row(page, 255, xs, ["", "", "", "", "", "", "", "", "12.50", "3", "6", ""])
    doc.save(path)
    doc.close()
    return path
