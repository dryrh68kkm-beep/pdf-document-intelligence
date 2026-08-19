"""TextExtractor: per-word bounding-box extraction + text-layer quality validation.

Never trust the text layer just because it exists (proposal §4). After
pulling words+boxes from pdfplumber, we score each page's text quality;
pages below `text_quality_ocr_threshold` are flagged so the pipeline can
route them to OCR cross-check (or, when OCR is out of scope, so any field
sourced from that page can be marked NEEDS_REVIEW instead of trusted).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

from pdf_document_intelligence.config.settings import Settings

REPLACEMENT_CHAR = "�"

# Thai combining marks (vowels/tone marks that must follow a base consonant).
# Ranges per Unicode Thai block: sara a (U+0E31), the above/below vowel and
# tone-mark cluster (U+0E34-E3A), and the tone marks (U+0E47-E4E).
_THAI_COMBINING = set(
    [chr(0x0E31)] + [chr(c) for c in range(0x0E34, 0x0E3B)] + [chr(c) for c in range(0x0E47, 0x0E4F)]
)
_THAI_CONSONANT = set(chr(c) for c in range(0x0E01, 0x0E2F))
_THAI_VOWEL_LEADING = set(chr(c) for c in range(0x0E40, 0x0E45))  # sara e/ae/o/ai variants (precede consonant)
_THAI_BLOCK = set(chr(c) for c in range(0x0E01, 0x0E5C))


@dataclass
class Word:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    page: int


@dataclass
class TextQuality:
    printable_ratio: float
    thai_valid_ratio: float
    replacement_char_ratio: float
    thai_combining_density: float
    score: float
    reliable: bool


@dataclass
class PageText:
    page_number: int
    words: list[Word]
    raw_text: str
    quality: TextQuality


@dataclass
class DocumentText:
    pages: list[PageText] = field(default_factory=list)


def _printable_ratio(text: str) -> float:
    if not text:
        return 1.0
    printable = sum(1 for c in text if c.isprintable() or c.isspace())
    return printable / len(text)


def _replacement_char_ratio(text: str) -> float:
    if not text:
        return 0.0
    return text.count(REPLACEMENT_CHAR) / len(text)


def _thai_valid_ratio(text: str) -> float:
    """Fraction of Thai combining marks that are correctly attached to a
    preceding base consonant. A combining mark at string start, after a
    space, or after another combining mark (rather than a consonant) is a
    reordering/encoding defect — the classic "สระ/วรรณยุกต์แยก" failure."""
    combining_positions = [i for i, c in enumerate(text) if c in _THAI_COMBINING]
    if not combining_positions:
        return 1.0
    valid = 0
    for i in combining_positions:
        prev = text[i - 1] if i > 0 else ""
        if prev in _THAI_CONSONANT or prev in _THAI_COMBINING:
            valid += 1
    return valid / len(combining_positions)


def _thai_combining_density(text: str) -> float | None:
    """Fraction of Thai-block characters that are combining vowels/tone
    marks. Real Thai prose reliably carries a substantial share of these
    (สระบน/ล่าง, วรรณยุกต์) — a Thai-heavy passage with ~zero combining
    marks means the source font's glyph-to-Unicode map is dropping them
    entirely (silent character loss, not just reordering). Returns None
    when there isn't enough Thai text to judge (avoids false positives on
    short strings/labels)."""
    thai_chars = [c for c in text if 0x0E01 <= ord(c) <= 0x0E5B]
    if len(thai_chars) < 40:
        return None
    combining = sum(1 for c in thai_chars if c in _THAI_COMBINING)
    return combining / len(thai_chars)


def score_text_quality(text: str, settings: Settings) -> TextQuality:
    printable = _printable_ratio(text)
    thai_valid = _thai_valid_ratio(text)
    replacement = _replacement_char_ratio(text)
    combining_density = _thai_combining_density(text)

    # Simple weighted composite; any single hard failure (lots of replacement
    # chars, or Thai combining marks silently dropped) drags the score down
    # sharply rather than being averaged away.
    score = (printable * 0.3) + (thai_valid * 0.4) + ((1 - replacement) * 0.15)
    density_ok = True
    if combining_density is not None:
        density_ok = combining_density >= settings.min_thai_combining_density
        score += (min(combining_density / settings.min_thai_combining_density, 1.0)) * 0.15
    else:
        score += 0.15

    reliable = (
        printable >= settings.min_printable_char_ratio
        and thai_valid >= settings.min_thai_valid_char_ratio
        and replacement <= settings.max_replacement_char_ratio
        and density_ok
        and score >= settings.text_quality_ocr_threshold
    )
    return TextQuality(
        printable_ratio=printable,
        thai_valid_ratio=thai_valid,
        replacement_char_ratio=replacement,
        thai_combining_density=combining_density if combining_density is not None else -1.0,
        score=score,
        reliable=reliable,
    )


def extract_document_text(path: Path, settings: Settings, on_page_done=None) -> DocumentText:
    doc = DocumentText()
    with pdfplumber.open(str(path)) as pdf:
        total_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            page_number = i + 1
            raw_words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
            words = [
                Word(
                    text=unicodedata.normalize("NFC", w["text"]),
                    x0=w["x0"],
                    top=w["top"],
                    x1=w["x1"],
                    bottom=w["bottom"],
                    page=page_number,
                )
                for w in raw_words
            ]
            raw_text = page.extract_text() or ""
            quality = score_text_quality(raw_text, settings)
            doc.pages.append(PageText(page_number=page_number, words=words, raw_text=raw_text, quality=quality))
            if on_page_done:
                on_page_done(page_number, total_pages)
    return doc
