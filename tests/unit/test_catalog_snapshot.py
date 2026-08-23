"""Regression tests for one-time external master import."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from pdf_document_intelligence.catalog.snapshot import import_catalog_snapshot


def _write_external_master(path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "BARCODE",
                "ART_SV_NAME",
                "SUBCLASS_NAME",
                "ART_NO",
                "DEPARTMENT_NAME",
                "DIVISION_NAME",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "BARCODE": "990000000001",
                "ART_SV_NAME": "SYNTHETIC PRODUCT",
                "SUBCLASS_NAME": "SYNTHETIC SUBCLASS",
                "ART_NO": "990001",
                "DEPARTMENT_NAME": "99 SYNTHETIC DEPARTMENT",
                "DIVISION_NAME": "09 SYNTHETIC DIVISION",
            }
        )


def test_external_master_is_compiled_once_and_source_can_be_removed(tmp_path: Path):
    source = tmp_path / "external_master.csv"
    snapshot = tmp_path / "private" / "master_catalog.snapshot.json"
    _write_external_master(source)

    result = import_catalog_snapshot(source, snapshot_path=snapshot)
    assert result == snapshot
    assert snapshot.is_file()

    source.unlink()
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["products"] == [
        {
            "barcode": "990000000001",
            "name": "SYNTHETIC PRODUCT",
            "structure": "SYNTHETIC SUBCLASS",
            "root_code": "990001",
        }
    ]
    assert payload["department_divisions"] == {
        "99 SYNTHETIC DEPARTMENT": "09 SYNTHETIC DIVISION"
    }


def test_existing_snapshot_is_not_overwritten_without_explicit_refresh(tmp_path: Path):
    source = tmp_path / "external_master.csv"
    snapshot = tmp_path / "master_catalog.snapshot.json"
    _write_external_master(source)
    import_catalog_snapshot(source, snapshot_path=snapshot)
    first = snapshot.read_bytes()

    source.write_text(
        "BARCODE,ART_SV_NAME,SUBCLASS_NAME,ART_NO,DEPARTMENT_NAME,DIVISION_NAME\n"
        "990000000002,CHANGED PRODUCT,CHANGED,990002,99 CHANGED,09 CHANGED\n",
        encoding="utf-8",
    )
    import_catalog_snapshot(source, snapshot_path=snapshot)
    assert snapshot.read_bytes() == first


def test_cp874_encoded_source_decodes_thai_text_correctly(tmp_path: Path):
    # Real store master exports have shown up in the Windows Thai codepage
    # (cp874/TIS-620), not just UTF-8. Decoding as UTF-8 with errors="replace"
    # doesn't raise - it silently turns every Thai character into U+FFFD,
    # producing mojibake product names throughout the catalog. Regression for
    # that exact symptom, seen in practice after an in-web CSV re-import.
    source = tmp_path / "external_master_cp874.csv"
    snapshot = tmp_path / "master_catalog.snapshot.json"
    with source.open("w", encoding="cp874", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["BARCODE", "ART_SV_NAME", "SUBCLASS_NAME", "ART_NO", "DEPARTMENT_NAME", "DIVISION_NAME"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "BARCODE": "990000000003",
                "ART_SV_NAME": "รองเท้าผ้าใบ สีแดง S38",
                "SUBCLASS_NAME": "FOOTWEAR",
                "ART_NO": "990003",
                "DEPARTMENT_NAME": "99 SYNTHETIC DEPARTMENT",
                "DIVISION_NAME": "09 SYNTHETIC DIVISION",
            }
        )

    import_catalog_snapshot(source, snapshot_path=snapshot)
    payload = json.loads(snapshot.read_text(encoding="utf-8"))
    assert payload["products"][0]["name"] == "รองเท้าผ้าใบ สีแดง S38"
    assert "�" not in payload["products"][0]["name"]
