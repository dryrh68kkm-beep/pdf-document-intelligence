"""Offline expiry-dashboard link: CSV parsing + barcode-price matching in
catalog/expiry_link.py, exercised directly against real temp files (no
FastAPI app, no database) - fast and deterministic.
"""
from __future__ import annotations

from pathlib import Path

from pdf_document_intelligence.catalog import expiry_link


def _write_csv(path: Path, rows: list[str], encoding: str = "utf-8-sig") -> None:
    header = "BAR_CODE,DESCRIPTION,STOCK_QTY,DAY_LEFT,SUB_DEPT_NAME,DIV,DEPT\n"
    path.write_text(header + "\n".join(rows) + "\n", encoding=encoding)


def test_configured_source_path_none_when_env_unset(monkeypatch):
    monkeypatch.delenv(expiry_link.EXPIRY_LINK_ENV, raising=False)
    assert expiry_link.configured_source_path() is None


def test_configured_source_path_from_env(monkeypatch, tmp_path):
    target = tmp_path / "NEARLY_EXPIRED_1003.csv"
    monkeypatch.setenv(expiry_link.EXPIRY_LINK_ENV, str(target))
    assert expiry_link.configured_source_path() == target


def test_read_near_expiry_rows_missing_file_returns_empty(tmp_path):
    assert expiry_link.read_near_expiry_rows(tmp_path / "missing.csv") == []


def test_read_near_expiry_rows_parses_expected_columns(tmp_path):
    csv_path = tmp_path / "NEARLY_EXPIRED_1003.csv"
    _write_csv(csv_path, ["8850001,ทดสอบสินค้า,10,5,SUB,D01,DEPT1"])
    rows = expiry_link.read_near_expiry_rows(csv_path)
    assert rows == [
        {
            "barcode": "8850001",
            "description": "ทดสอบสินค้า",
            "stockQty": "10",
            "dayLeft": "5",
            "subDeptName": "SUB",
            "div": "D01",
            "dept": "DEPT1",
        }
    ]


def test_read_near_expiry_rows_skips_rows_without_barcode(tmp_path):
    csv_path = tmp_path / "NEARLY_EXPIRED_1003.csv"
    _write_csv(csv_path, [",no barcode,1,1,SUB,D01,DEPT1", "8850002,has barcode,2,2,SUB,D01,DEPT1"])
    rows = expiry_link.read_near_expiry_rows(csv_path)
    assert [r["barcode"] for r in rows] == ["8850002"]


def test_read_near_expiry_rows_decodes_cp874(tmp_path):
    csv_path = tmp_path / "NEARLY_EXPIRED_1003.csv"
    _write_csv(csv_path, ["8850003,ผลไม้,3,3,SUB,D01,DEPT1"], encoding="cp874")
    rows = expiry_link.read_near_expiry_rows(csv_path)
    assert rows[0]["description"] == "ผลไม้"


def test_build_summary_not_configured():
    summary = expiry_link.build_summary(None, {})
    assert summary == {
        "configured": False, "available": False, "fileFound": False,
        "itemCount": 0, "matchedCount": 0, "unmatchedCount": 0, "totalValue": 0.0,
    }


def test_build_summary_configured_but_file_missing(tmp_path):
    summary = expiry_link.build_summary(tmp_path / "missing.csv", {})
    assert summary["configured"] is True
    assert summary["available"] is False
    assert summary["fileFound"] is False
    assert summary["itemCount"] == 0


def test_build_summary_matches_by_barcode_and_computes_value(tmp_path):
    csv_path = tmp_path / "NEARLY_EXPIRED_1003.csv"
    _write_csv(
        csv_path,
        [
            "8850001,Product A,10,5,SUB,D01,DEPT1",
            "8850002,Product B,4,2,SUB,D01,DEPT1",
        ],
    )
    price_by_barcode = {"8850001": 12.5}  # 8850002 has no known price
    summary = expiry_link.build_summary(csv_path, price_by_barcode)
    assert summary["configured"] is True
    assert summary["available"] is True
    assert summary["fileFound"] is True
    assert summary["itemCount"] == 2
    assert summary["matchedCount"] == 1
    assert summary["unmatchedCount"] == 1
    assert summary["totalValue"] == 125.0


def test_build_summary_tolerates_non_numeric_stock_qty(tmp_path):
    csv_path = tmp_path / "NEARLY_EXPIRED_1003.csv"
    _write_csv(csv_path, ["8850001,Product A,not-a-number,5,SUB,D01,DEPT1"])
    summary = expiry_link.build_summary(csv_path, {"8850001": 9.0})
    assert summary["matchedCount"] == 1
    assert summary["totalValue"] == 0.0
