"""Locale-aware type parsing. Raw value is always preserved by the caller
(FieldParser) alongside whatever this module returns — this module never
discards information, it only proposes a parsed value.

Code fields (SKU/barcode/document numbers) must never pass through here as
numbers — the caller keeps them as `type="code"` strings so leading zeros
survive (proposal §23).
"""
from __future__ import annotations

import re

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

_NUMBER_RE = re.compile(r"^\(?-?[\d,]+(\.\d+)?\)?$")


class TypeParseError(Exception):
    pass


def normalize_digits(text: str) -> str:
    """Thai digits -> Arabic digits. Does not touch anything else."""
    return text.translate(_THAI_DIGITS)


def parse_number(raw: str) -> float:
    """Parses '1,234.50', '(1,234.50)' (accounting negative), '-1,234.50',
    '฿1,234' into a float. Raises TypeParseError rather than guessing when
    the format is ambiguous (e.g. could be thousands-sep or decimal-sep
    depending on locale) — caller must treat that as NEEDS_REVIEW, not
    silently pick one."""
    text = normalize_digits(raw).strip()
    text = text.replace("฿", "").replace(" ", "")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    if text.startswith("-"):
        negative = True
        text = text[1:]
    if not _NUMBER_RE.match(f"{text}") and not re.match(r"^[\d,]+(\.\d+)?$", text):
        raise TypeParseError(f"Cannot parse number from {raw!r}")
    # Thai/international convention assumed here: ',' = thousands, '.' = decimal.
    # A format like '1.234,50' (comma-decimal) would need locale context this
    # module doesn't have — reject rather than guess.
    if text.count(".") > 1:
        raise TypeParseError(f"Ambiguous decimal separators in {raw!r}")
    cleaned = text.replace(",", "")
    try:
        value = float(cleaned)
    except ValueError as exc:
        raise TypeParseError(f"Cannot parse number from {raw!r}") from exc
    return -value if negative else value


def parse_integer(raw: str) -> int:
    value = parse_number(raw)
    if not value.is_integer():
        raise TypeParseError(f"{raw!r} is not an integer")
    return int(value)
