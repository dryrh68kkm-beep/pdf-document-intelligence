"""Template auto-detection (proposal §38/§41, hand-rolled fingerprint
rather than a learned matcher): tries each registered template's header
column signature against the first few pages and returns whichever
matches. A real TemplateMatcher would fingerprint on more than the header
row (page size, anchor text blocks, column count) — this is deliberately
minimal until there's a third template to force that generalization.
"""
from __future__ import annotations

from pdf_document_intelligence.extract.text import DocumentText
from pdf_document_intelligence.tables.geometry import find_header_on_page
from pdf_document_intelligence.templates.packing_list_bigc import COLUMNS as BIGC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bigc import TEMPLATE_ID as BIGC_TEMPLATE_ID
from pdf_document_intelligence.templates.packing_list_bpdc import COLUMNS as BPDC_COLUMNS
from pdf_document_intelligence.templates.packing_list_bpdc import TEMPLATE_ID as BPDC_TEMPLATE_ID

UNKNOWN_TEMPLATE = "UNKNOWN_LAYOUT"
_PAGES_TO_CHECK = 3


def detect_template(doc_text: DocumentText) -> str:
    for page in doc_text.pages[:_PAGES_TO_CHECK]:
        if find_header_on_page(page, BIGC_COLUMNS) is not None:
            return BIGC_TEMPLATE_ID
        if find_header_on_page(page, BPDC_COLUMNS) is not None:
            return BPDC_TEMPLATE_ID
    return UNKNOWN_TEMPLATE
