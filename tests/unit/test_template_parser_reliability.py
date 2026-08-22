from pdf_document_intelligence.extract.text import DocumentText, PageText, TextQuality, Word
from pdf_document_intelligence.tables.reconstruct import _find_department, _find_total_row
from pdf_document_intelligence.templates.detect import UNKNOWN_TEMPLATE, detect_template
from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS as BIGC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bigc import TEMPLATE_ID as BIGC_TEMPLATE_ID
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


def _page(page_number: int, texts: list[str], top: float = 100.0) -> PageText:
    words = []
    x = 10.0
    for text in texts:
        width = max(8.0, len(text) * 4.0)
        words.append(Word(text=text, x0=x, top=top, x1=x + width, bottom=top + 10.0, page=page_number))
        x += width + 8.0
    return PageText(page_number=page_number, words=words, raw_text=" ".join(texts), quality=_quality())


def _header_tokens(columns) -> list[str]:
    return [token for column in columns for token in column.header_tokens]


def test_detects_bigc_from_late_header_page():
    doc = DocumentText(pages=[_page(1, ["cover", "page"]), _page(2, _header_tokens(BIGC_COLUMNS))])
    assert detect_template(doc) == BIGC_TEMPLATE_ID


def test_detects_bpdc_when_only_bpdc_header_is_present():
    doc = DocumentText(pages=[_page(1, _header_tokens(BPDC_COLUMNS))])
    assert detect_template(doc) == BPDC_TEMPLATE_ID


def test_mixed_complete_headers_are_routed_to_unknown_layout():
    doc = DocumentText(
        pages=[
            _page(1, _header_tokens(BIGC_COLUMNS)),
            _page(2, _header_tokens(BPDC_COLUMNS)),
        ]
    )
    assert detect_template(doc) == UNKNOWN_TEMPLATE


def test_bigc_department_label_tolerates_case_and_punctuation():
    page = _page(1, ["DEPARTMENT:", "HOME", "LINE"])
    assert _find_department(page) == "HOME LINE"


def test_bigc_total_label_tolerates_case_and_punctuation():
    page = _page(1, ["TOTAL:", "12", "100.0"])
    row = _find_total_row(page)
    assert row is not None
    assert row[0].text == "Total"
