"""Security-safe regression coverage for the BPDC packing-list layout.

The PDF is generated at test runtime from fictional values; no operational
packing list, barcode catalog, or expected-output dump is committed.
"""
from __future__ import annotations

import pytest

from pdf_document_intelligence.pipeline.orchestrator import process_document
from tests.synthetic_documents import make_bpdc_pdf


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    path = tmp_path_factory.mktemp("synthetic-bpdc") / "bpdc.pdf"
    return process_document(make_bpdc_pdf(path))


def test_template_detected_as_bpdc(result):
    assert result.document_type == "packing_list_bpdc"
    assert result.pages == 1


def test_department_and_row_shape(result):
    assert len(result.tables) == 1
    assert result.tables[0].name == "SYNTHETIC BEVERAGE"
    assert len(result.tables[0].rows) == 1
    assert result.tables[0].rows[0].row_index == 1


def test_numeric_and_code_fields_are_extracted_from_pdf_text(result):
    row = result.tables[0].rows[0]
    expected = {
        "dn_no": "110001",
        "do_no": "210001",
        "order_no": "310001",
        "line": 1,
        "article": "87654321-00-001",
        "barcode": "9990000000002",
        "weight_qty": 12.5,
        "pu_qty": 3,
        "sku_qty": 6,
    }
    for field_name, value in expected.items():
        assert row.fields[field_name].value == value
        assert row.fields[field_name].source == "pdf_text"


def test_foc_remark_remains_inventory_metadata(result):
    row = result.tables[0].rows[0]
    assert row.fields["remarks"].value == "FOC"
    assert row.suspected_non_product is False


def test_document_reconciles(result):
    assert result.validation.reconciled is True
    assert result.validation.errors == []


def test_no_master_catalog_guessing_without_external_master(result):
    row = result.tables[0].rows[0]
    assert row.fields["name"].value == "Synthetic Product B"
    assert row.fields["name"].source in {"pdf_text", "ocr", "cross_validated"}
    assert row.fields["name"].source != "master_catalog"
