"""Thai text normalization. Never auto-"fixes" ambiguous text (proposal
§7/§46) — this only does lossless, reversible normalization (NFC, visible
zero-width/whitespace cleanup) and keeps the original alongside it. Actual
character-level correction (e.g. reordering, glyph substitution) is not
attempted here; that's a job for OCR cross-check + human review, not silent
normalization.
"""
from __future__ import annotations

import unicodedata

_ZERO_WIDTH = "​‌‍﻿"
_NBSP = " "


def normalize_thai_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", raw)
    for ch in _ZERO_WIDTH:
        text = text.replace(ch, "")
    text = text.replace(_NBSP, " ")
    return text.strip()
