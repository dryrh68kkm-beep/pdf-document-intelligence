"""Template auto-detection for the two supported Packing List layouts.

Detection stays header/geometry driven, but it must not assume the first
three pages always contain a usable table header. Some exports begin with
cover/continuation content before the first full header. Text for every
page is already extracted before this function runs, so scanning the
remaining pages adds no OCR work.
"""
from __future__ import annotations

from pdf_document_intelligence.extract.text import DocumentText
from pdf_document_intelligence.tables.geometry import find_header_on_page
from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS as BIGC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bigc import TEMPLATE_ID as BIGC_TEMPLATE_ID
from pdf_document_intelligence.templates.packing_list_bpdc import COLUMNS as BPDC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bpdc import TEMPLATE_ID as BPDC_TEMPLATE_ID

UNKNOWN_TEMPLATE = "UNKNOWN_LAYOUT"


def detect_template(doc_text: DocumentText) -> str:
    # Do not cap this at the first N pages. This is text-layer inspection
    # only; no OCR is triggered here. The first complete table header wins.
    for page in doc_text.pages:
        if find_header_on_page(page, BIGC_COLUMNS) is not None:
            return BIGC_TEMPLATE_ID
        if find_header_on_page(page, BPDC_COLUMNS) is not None:
            return BPDC_TEMPLATE_ID
    return UNKNOWN_TEMPLATE
