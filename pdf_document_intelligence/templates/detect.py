"""Template auto-detection for the supported Packing List layouts.

Detection is evidence-based across the whole extracted document. We do not
pick a parser merely because the first complete header happens to resemble
one layout: mixed or contradictory layout evidence is routed to
``UNKNOWN_LAYOUT`` so the pipeline cannot silently parse with the wrong
reconstructor.
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
    """Return one unambiguous registered template, otherwise UNKNOWN.

    Every page has already gone through text extraction before detection, so
    scanning all pages adds no OCR cost. Evidence from all complete headers
    is collected first. A single-layout document can have its first usable
    header on any page; a document carrying complete headers from both
    layouts is treated as ambiguous instead of using a potentially wrong
    parser for part of the file.
    """
    matched_templates: set[str] = set()

    for page in doc_text.pages:
        if find_header_on_page(page, BIGC_COLUMNS) is not None:
            matched_templates.add(BIGC_TEMPLATE_ID)
        if find_header_on_page(page, BPDC_COLUMNS) is not None:
            matched_templates.add(BPDC_TEMPLATE_ID)

        if len(matched_templates) > 1:
            return UNKNOWN_TEMPLATE

    if len(matched_templates) == 1:
        return next(iter(matched_templates))
    return UNKNOWN_TEMPLATE
