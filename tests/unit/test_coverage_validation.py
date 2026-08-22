from pdf_document_intelligence.extract.text import DocumentText, PageText, TextQuality, Word
from pdf_document_intelligence.tables.reconstruct import RawTable
from pdf_document_intelligence.tables.reconstruct_bpdc import PalletBlock
from pdf_document_intelligence.validate.coverage import validate_bigc_coverage, validate_bpdc_coverage


def _quality() -> TextQuality:
    return TextQuality(
        printable_ratio=1.0,
        thai_valid_ratio=1.0,
        replacement_char_ratio=0.0,
        thai_combining_density=-1.0,
        score=1.0,
        reliable=True,
    )


def _page(page_number: int, *texts: str) -> PageText:
    words = [
        Word(text=text, x0=float(i * 20), top=200.0, x1=float(i * 20 + 15), bottom=210.0, page=page_number)
        for i, text in enumerate(texts)
    ]
    return PageText(page_number=page_number, words=words, raw_text=" ".join(texts), quality=_quality())


def _codes(issues):
    return {issue.code for issue in issues}


def test_page_count_mismatch_is_error():
    doc = DocumentText(pages=[_page(1, "cover")])

    issues = validate_bigc_coverage(doc, expected_page_count=2, raw_tables=[], extracted_tables=[])

    assert "PAGE_COUNT_MISMATCH" in _codes(issues)
    assert any(issue.code == "PAGE_COUNT_MISMATCH" and issue.severity == "error" for issue in issues)


def test_supported_document_with_zero_rows_is_error():
    doc = DocumentText(pages=[_page(1, "cover")])

    issues = validate_bpdc_coverage(doc, expected_page_count=1, pallet_blocks=[], extracted_tables=[])

    assert "ZERO_PRODUCT_ROWS" in _codes(issues)


def test_article_evidence_without_parsed_row_is_error_bigc():
    doc = DocumentText(pages=[_page(1, "1234567-89-012")])

    issues = validate_bigc_coverage(doc, expected_page_count=1, raw_tables=[], extracted_tables=[])

    assert "PAGE_DATA_MISSING" in _codes(issues)


def test_empty_bigc_table_is_error():
    doc = DocumentText(pages=[_page(1, "cover")])
    raw = RawTable(department="FRESH FOOD", page_start=1, page_end=1, rows=[])

    issues = validate_bigc_coverage(doc, expected_page_count=1, raw_tables=[raw], extracted_tables=[])

    assert "EMPTY_TABLE" in _codes(issues)


def test_empty_bpdc_pallet_block_is_error():
    doc = DocumentText(pages=[_page(1, "cover")])
    block = PalletBlock(pallet_no="P001", lot_no=None, page_start=1, page_end=1, rows=[])

    issues = validate_bpdc_coverage(doc, expected_page_count=1, pallet_blocks=[block], extracted_tables=[])

    assert "EMPTY_PALLET_BLOCK" in _codes(issues)


def test_missing_bpdc_pallet_identifier_is_warning():
    doc = DocumentText(pages=[_page(1, "cover")])
    block = PalletBlock(pallet_no="", lot_no=None, page_start=1, page_end=1, rows=[])

    issues = validate_bpdc_coverage(doc, expected_page_count=1, pallet_blocks=[block], extracted_tables=[])

    assert any(issue.code == "PALLET_ID_MISSING" and issue.severity == "warning" for issue in issues)
