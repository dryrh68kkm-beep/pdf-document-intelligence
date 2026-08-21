"""Evidence-backed document-date extraction.

Only dates next to an explicit document/date label are accepted. Manufacturing,
expiry and lot dates are deliberately excluded: they describe a product, not
the transaction document, and must never drive Dashboard filtering.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from pdf_document_intelligence.extract.text import DocumentText

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_DATE_VALUE = r"(?P<value>\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}[/-]\d{1,2}[/-]\d{1,2})"
_LABELS = (
    ("Document Date", r"\bdocument\s*date\b"),
    ("Delivery Date", r"\b(?:delivery|shipment)\s*date\b"),
    ("วันที่เอกสาร", r"วันที่\s*(?:เอกสาร|ส่งสินค้า|จัดส่ง)"),
    ("วันที่", r"วัน\s*ที่"),
    ("Date", r"\bdate\b"),
)
_EXCLUDED_CONTEXT = re.compile(
    r"\b(?:mfg|manufactur(?:e|ing)|exp(?:iry|iration)?|best\s*before|lot)\b|"
    r"(?:วันผลิต|ผลิตเมื่อ|วันหมดอายุ|หมดอายุ)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocumentDateMatch:
    value: date
    raw_value: str
    label: str
    page: int


def _parse_date(raw: str) -> date | None:
    parts = raw.translate(_THAI_DIGITS).replace("-", "/").split("/")
    try:
        if len(parts) != 3:
            return None
        if len(parts[0]) == 4:
            year, month, day = (int(part) for part in parts)
        else:
            day, month, year = (int(part) for part in parts)
        if year < 100:
            year += 2000
        if year >= 2400:  # Thai Buddhist Era -> Gregorian calendar
            year -= 543
        return date(year, month, day)
    except ValueError:
        return None


def extract_document_date(document_text: DocumentText) -> DocumentDateMatch | None:
    """Find the highest-priority labelled transaction date in the PDF text.

    No fallback guesses from filenames, upload timestamps, MFG, expiry, or lot
    codes are made. If no labelled transaction date is found, return None so
    the UI can surface that the document needs review/reprocessing.
    """
    for label, label_pattern in _LABELS:
        pattern = re.compile(
            rf"(?P<label>{label_pattern})\s*(?:[:：#]|\-|\s)*{_DATE_VALUE}",
            re.IGNORECASE,
        )
        for page in document_text.pages:
            text = page.raw_text.translate(_THAI_DIGITS)
            for match in pattern.finditer(text):
                context = text[max(0, match.start() - 48):match.end()]
                if _EXCLUDED_CONTEXT.search(context):
                    continue
                parsed = _parse_date(match.group("value"))
                if parsed:
                    return DocumentDateMatch(
                        value=parsed,
                        raw_value=match.group("value"),
                        label=label,
                        page=page.page_number,
                    )
    return None
