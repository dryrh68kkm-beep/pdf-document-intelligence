"""unit_price/amount resolution from the master catalog's CURRENT_COST
column (user-requested: previously always None since no packing-list
template extracts a price - now resolved the same way `name` already is,
by exact barcode match against the same catalog snapshot). Decimal
throughout per the existing "no float money math" rule."""
from __future__ import annotations

import csv

import pytest

from pdf_document_intelligence.api.rows import prepare_flat_rows
from pdf_document_intelligence.catalog import loader as loader_module
from pdf_document_intelligence.catalog import snapshot as snapshot_module
from pdf_document_intelligence.db.connection import open_independent_connection
from pdf_document_intelligence.db.repository import Repository
from tests.unit.db_helpers import make_result, make_row


@pytest.fixture()
def catalog_with_cost(tmp_path, monkeypatch):
    source = tmp_path / "external_master.csv"
    with source.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "BARCODE", "ART_SV_NAME", "SUBCLASS_NAME", "ART_NO",
                "DEPARTMENT_NAME", "DIVISION_NAME", "CURRENT_COST",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "BARCODE": "BC1", "ART_SV_NAME": "Product 1", "SUBCLASS_NAME": "SUB",
            "ART_NO": "ART1", "DEPARTMENT_NAME": "HBA", "DIVISION_NAME": "04 DRY FOOD",
            "CURRENT_COST": "15.50",
        })
        writer.writerow({
            "BARCODE": "BC2", "ART_SV_NAME": "Product 2", "SUBCLASS_NAME": "SUB",
            "ART_NO": "ART2", "DEPARTMENT_NAME": "HBA", "DIVISION_NAME": "04 DRY FOOD",
            "CURRENT_COST": "",
        })
        writer.writerow({
            "BARCODE": "BC3", "ART_SV_NAME": "Product 3", "SUBCLASS_NAME": "SUB",
            "ART_NO": "ART3", "DEPARTMENT_NAME": "HBA", "DIVISION_NAME": "04 DRY FOOD",
            "CURRENT_COST": "not-a-number",
        })

    data_dir = tmp_path / "data_dir"
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(data_dir))

    snapshot_module.import_catalog_snapshot(source, overwrite=True)
    loader_module.get_default_catalog.cache_clear()
    yield
    loader_module.get_default_catalog.cache_clear()


def _repo(tmp_path):
    return Repository(open_independent_connection(tmp_path / "t.db"))


def test_unit_price_and_amount_resolved_from_catalog_cost(catalog_with_cost, tmp_path):
    tables = [("HBA", [make_row(0, "HBA", "BC1", "ART1", "Product 1", 10.0, 2, 20)])]
    result = make_result("doc-1", "t.pdf", tables)
    flat = prepare_flat_rows("doc-1", result, _repo(tmp_path))
    assert len(flat) == 1
    assert flat[0]["unit_price"] == 15.50
    assert flat[0]["amount"] == 310.00  # 15.50 * sku_qty(20)


def test_unit_price_none_when_catalog_cost_blank(catalog_with_cost, tmp_path):
    tables = [("HBA", [make_row(0, "HBA", "BC2", "ART2", "Product 2", 10.0, 2, 20)])]
    result = make_result("doc-1", "t.pdf", tables)
    flat = prepare_flat_rows("doc-1", result, _repo(tmp_path))
    assert flat[0]["unit_price"] is None
    assert flat[0]["amount"] is None


def test_unit_price_none_when_catalog_cost_unparseable(catalog_with_cost, tmp_path):
    tables = [("HBA", [make_row(0, "HBA", "BC3", "ART3", "Product 3", 10.0, 2, 20)])]
    result = make_result("doc-1", "t.pdf", tables)
    flat = prepare_flat_rows("doc-1", result, _repo(tmp_path))
    assert flat[0]["unit_price"] is None
    assert flat[0]["amount"] is None


def test_unit_price_none_when_barcode_not_in_catalog(catalog_with_cost, tmp_path):
    tables = [("HBA", [make_row(0, "HBA", "BC_UNKNOWN", "ART9", "Unknown", 10.0, 2, 20)])]
    result = make_result("doc-1", "t.pdf", tables)
    flat = prepare_flat_rows("doc-1", result, _repo(tmp_path))
    assert flat[0]["unit_price"] is None
    assert flat[0]["amount"] is None


def test_unit_price_and_amount_surfaced_in_fields_dict_for_api_and_evidence_panel(catalog_with_cost, tmp_path):
    # The flat unit_price/amount columns alone aren't enough: the Products
    # table and the Evidence panel both read every field through
    # row["fields"][name] (product_row_json/_field_json), so unit_price and
    # amount must also appear there as FieldValue-shaped entries, or the API
    # response and the correction/edit UI never see them at all.
    tables = [("HBA", [make_row(0, "HBA", "BC1", "ART1", "Product 1", 10.0, 2, 20)])]
    result = make_result("doc-1", "t.pdf", tables)
    flat = prepare_flat_rows("doc-1", result, _repo(tmp_path))
    fields = flat[0]["fields"]
    assert fields["unit_price"]["value"] == 15.50
    assert fields["unit_price"]["source"] == "master_catalog"
    assert fields["amount"]["value"] == 310.00
    assert fields["amount"]["source"] == "master_catalog"
