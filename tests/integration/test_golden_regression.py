"""Security-safe regression coverage for the Big C packing-list layout.

No real/company PDF or expected-output dump is stored in the repository.
The document is generated at runtime from fictional values.
"""
from __future__ import annotations

import pytest

from pdf_document_intelligence.pipeline.orchestrator import process_document
from tests.synthetic_documents import make_bigc_pdf


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    path = tmp_path_factory.mktemp("synthetic-bigc") / "bigc.pdf"
    return process_document(make_bigc_pdf(path))


def test_template_and_document_shape(result):
    assert result.document_type == "packing_list_bigc_cdc"
    assert result.pages == 1
    assert len(result.tables) == 1
    assert result.tables[0].name == "SYNTHETIC FOOD"
    assert len(result.tables[0].rows) == 1


def test_numeric_and_code_fields_are_extracted_from_pdf_text(result):
    row = result.tables[0].rows[0]
    expected = {
        "dn_no": "100001",
        "do_no": "200001",
        "order_no": "300001",
        "line": 1,
        "pallet": "P001",
        "lot": "L001",
        "article": "12345678-00-001",
        "barcode": "9990000000001",
        "weight_qty": 10.0,
        "pu_qty": 2,
        "sku_qty": 4,
    }
    for field_name, value in expected.items():
        assert row.fields[field_name].value == value
        assert row.fields[field_name].source == "pdf_text"


def test_synthetic_name_is_preserved_without_master_guessing(result):
    row = result.tables[0].rows[0]
    assert row.fields["name"].value == "Synthetic Product A"
    assert row.fields["name"].source in {"pdf_text", "ocr", "cross_validated"}
    assert row.fields["name"].source != "master_catalog"


def test_document_reconciles(result):
    assert result.validation.reconciled is True
    assert result.validation.errors == []


def test_no_synthetic_row_is_misclassified_as_non_product(result):
    assert result.tables[0].rows[0].suspected_non_product is False
