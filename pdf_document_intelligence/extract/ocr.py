"""OCRService: page/region-scoped OCR fallback for text-layer defects that
extraction-side fixes cannot recover from.

Root cause this exists for (proposal §4/§10, confirmed by direct inspection
of the golden sample, not inferred from symptoms): the sample's embedded
Tahoma subset font has a `ToUnicode` CMap whose codespace covers only 115
glyph codes, and none of them map to a Thai combining vowel or tone mark —
those glyphs were never entered into the CMap's bfrange table when the PDF
was generated. Rendering the *same* font at 300dpi shows the glyphs draw
correctly (visually complete Thai), which proves this is a ToUnicode
mapping defect, not a missing/corrupt font program — text extraction can
never recover those characters because the character identity data simply
isn't present in the content stream, no matter how extraction logic is
improved. OCR-of-the-rendered-page is therefore not a workaround but the
only source that can see the actual glyphs.

Renders are cached per (path, page_number, dpi) so multiple region OCR
calls on the same page (e.g. many rows' Name cells) only rasterize once.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytesseract
from PIL import Image

try:
    import pymupdf as fitz  # supported PyMuPDF import name
except ImportError:  # pragma: no cover
    fitz = None

_PAGE_CACHE: dict[tuple[str, int, int], Image.Image] = {}

DEFAULT_DPI = 300
# Small-text documents (spec §8) may need a higher render DPI; callers can
# pass this explicitly rather than us silently upscaling pixels, which adds
# CPU without adding real information.
SMALL_TEXT_DPI = 400


@dataclass
class OCRResult:
    text: str
    confidence: float  # 0.0-1.0, mean word-level confidence from tesseract
    engine: str = "tesseract"


def render_page(path: Path, page_number: int, dpi: int = DEFAULT_DPI) -> Image.Image:
    if fitz is None:
        raise RuntimeError("PyMuPDF (fitz) is required for OCR page rendering")
    key = (str(path), page_number, dpi)
    if key in _PAGE_CACHE:
        return _PAGE_CACHE[key]
    doc = fitz.open(str(path))
    try:
        page = doc[page_number - 1]
        zoom = dpi / 72
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
    _PAGE_CACHE[key] = image
    return image


def clear_page_cache() -> None:
    _PAGE_CACHE.clear()


def ocr_region(
    page_image: Image.Image,
    bbox_pdf_pts: tuple[float, float, float, float],  # (x0, top, x1, bottom) in PDF points
    dpi: int = DEFAULT_DPI,
    padding_pts: float = 6.0,
    lang: str = "tha+eng",
    upscale: int = 3,
) -> OCRResult:
    """OCRs one bounding-box region of an already-rendered page. Padding is
    added because a word bbox tightly cropped to glyph ink clips ascenders/
    descenders and Thai combining marks that extend above/below the
    baseline — the exact defect we're trying to recover from, so the crop
    must not reintroduce it."""
    scale = dpi / 72
    x0, top, x1, bottom = bbox_pdf_pts
    px0 = max(0, int((x0 - padding_pts) * scale))
    ptop = max(0, int((top - padding_pts) * scale))
    px1 = min(page_image.width, int((x1 + padding_pts) * scale))
    pbottom = min(page_image.height, int((bottom + padding_pts) * scale))
    if px1 <= px0 or pbottom <= ptop:
        return OCRResult(text="", confidence=0.0)

    crop = page_image.crop((px0, ptop, px1, pbottom))
    if upscale > 1:
        crop = crop.resize((crop.width * upscale, crop.height * upscale), Image.LANCZOS)

    # image_to_string (not a manual join of image_to_data's per-token text)
    # for the text itself: Thai script has no inter-word spaces, and
    # tesseract's word-level tokenization in `data` frequently splits a
    # single word into syllable-sized tokens — joining those with spaces
    # reintroduces spurious spacing tesseract's own line assembly doesn't
    # produce. `image_to_data` is used only for a confidence estimate.
    text = pytesseract.image_to_string(crop, lang=lang, config="--psm 7").strip()
    data = pytesseract.image_to_data(crop, lang=lang, config="--psm 7", output_type=pytesseract.Output.DICT)
    confidences = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
    mean_conf = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return OCRResult(text=text, confidence=mean_conf)
