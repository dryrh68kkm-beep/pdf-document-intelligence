"""Required, blocking real-OCR check for the Windows CI job.

Historically this was a `continue-on-error` step because chocolatey's
`tesseract` package on windows-latest did not reliably ship Thai (`tha`)
traineddata. That gap is now closed upstream of this file: the
`windows-e2e` workflow job installs Tesseract via chocolatey, then
downloads `tha.traineddata` straight from the official
`tesseract-ocr/tessdata_fast` repo and places it in Tesseract-OCR's
`tessdata` directory itself, and verifies `tesseract --list-langs`
reports both `eng` and `tha` *before* this file is ever run - see
`.github/workflows/tests.yml`. Because the workflow now guarantees a
Thai-capable Tesseract, every test in this file runs unconditionally: no
skip-if-Thai-missing behavior remains. If the workflow's guarantee is
ever broken, these tests are meant to go red, not skip.

Font risk: rendering Thai script for OCR depends on a Thai-capable font
being available, and which fonts ship on a given windows-latest image is
not something this repo can rely on staying constant. To keep this
deterministic regardless of the runner's installed font set, the test
below downloads a small, fixed, open-license Thai font (Noto Sans Thai)
at runtime into a temp directory - the same "fetch a known-good asset at
CI time instead of trusting what happens to be preinstalled" pattern used
for tha.traineddata - and never assumes a system font. Nothing here is
committed to the repo: no font file, no real company document, no real
Master data.
"""
from __future__ import annotations

import re
import urllib.request

import pytest
import pytesseract

# Small (~37KB), pinned, open-license (SIL OFL) Thai-script font fetched
# fresh at test time so this test does not depend on whatever fonts a
# given windows-latest/windows-2025 runner image happens to ship (that set
# is not documented anywhere this repo can pin against). Same trust model
# as the workflow's tha.traineddata download: an official upstream source
# fetched over HTTPS, not a font bundled into this repository.
_THAI_FONT_URL = (
    "https://raw.githubusercontent.com/googlefonts/noto-fonts/main/"
    "hinted/ttf/NotoSansThai/NotoSansThai-Regular.ttf"
)

# Unicode range for the Thai script block - used only to check that *some*
# Thai character came back from OCR, never to assert exact output (glyph
# rasterization differences between OSes/font-hinting make exact-text
# assertions flaky across platforms, which is explicitly out of scope
# here).
_THAI_CHAR_RE = re.compile(r"[฀-๿]")


@pytest.fixture(scope="module")
def thai_font_path(tmp_path_factory):
    dest = tmp_path_factory.mktemp("thai-ocr-font") / "NotoSansThai-Regular.ttf"
    urllib.request.urlretrieve(_THAI_FONT_URL, dest)
    assert dest.stat().st_size > 1000, "Thai font download looked truncated/empty"
    return dest


def test_health_endpoint_reports_thai_pack_available():
    from pdf_document_intelligence.api.health import check_health
    from pdf_document_intelligence.db.repository import get_repository

    result = check_health(get_repository())
    assert result["ocr"]["available"] is True
    assert result["ocr"]["thaiLanguagePack"]["available"] is True


def test_real_ocr_on_a_synthetic_english_image_does_not_crash():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (300, 80), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 25), "SYNTHETIC 12345", fill="black")

    text = pytesseract.image_to_string(img, lang="tha+eng")
    assert isinstance(text, str)


def test_real_ocr_on_a_synthetic_thai_image_does_not_crash(thai_font_path):
    """Renders real Thai text ("สินค้า ทดสอบ 12345" - "product test 12345")
    at runtime with Pillow using the downloaded Thai font, then runs it
    through the real Tesseract binary with lang="tha+eng". Deliberately
    does not assert an exact transcription - font rasterization can differ
    subtly across OSes/DPI, and an exact-match assertion would be exactly
    the kind of environment-dependent flakiness this test exists to avoid.
    Instead it asserts the structural bar the task requires: OCR runs
    without raising TesseractError, returns a string, and recognizes at
    least some Thai-script characters back out of Thai-script input.
    """
    from PIL import Image, ImageDraw, ImageFont
    from pytesseract import TesseractError

    font = ImageFont.truetype(str(thai_font_path), 32)
    img = Image.new("RGB", (500, 100), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((15, 30), "สินค้า ทดสอบ 12345", fill="black", font=font)

    try:
        text = pytesseract.image_to_string(img, lang="tha+eng")
    except TesseractError as exc:  # pragma: no cover - failure path
        pytest.fail(f"real Thai OCR raised TesseractError: {exc}")

    assert isinstance(text, str)
    assert _THAI_CHAR_RE.search(text), f"expected at least one Thai-script character in OCR output, got {text!r}"
