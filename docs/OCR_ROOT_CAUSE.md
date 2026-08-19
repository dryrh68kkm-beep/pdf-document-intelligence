# Root cause: garbled Thai product names in the golden sample

## Symptom

Product-name text extracted from `tests/golden/samples/PL92924_112520819.R211252100.pdf`
was garbled — consonants scrambled, all vowels/tone marks missing, e.g.
`มนบ เบคกน แฟนซซ` instead of `มินิเค้กแฟนซี`. Barcode/DN/DO/Order/weight/PU/SKU
fields (all ASCII digits) were unaffected.

## Audit trace (per-stage debug samples)

Traced the pipeline stage by stage on this file, capturing raw output at each step:

1. **Raw PDF text extraction** (`pdfplumber` word/char extraction, bypassing
   all of this project's own code) already returns the garbled string. This
   was checked directly against `pdfplumber`'s output before any of our
   `extract/text.py`, `normalize/thai.py`, or `tables/reconstruct.py` code
   runs on it.
2. **Reading order**: word bounding boxes are correctly ordered
   left-to-right, top-to-bottom (verified against the geometric table
   reconstruction, which independently reconstructs all 9 department tables
   with row/sum counts matching the document's own printed totals exactly —
   see `tests/integration/test_golden_regression.py`). Reading order is not
   the defect.
3. **Normalization** (`normalize/thai.py`): only does NFC + zero-width/NBSP
   cleanup; disabling it entirely does not change the garbling (confirmed —
   the raw pdfplumber string is already garbled before normalization runs).

This rules out categories B (TextItem ordering), C (normalization), D
(table reconstruction merging wrong cells), and E (browser/font rendering —
the corruption is in the extracted *string*, not a display issue). It
points at category A: the defect is in the PDF's own text layer.

## Definitive proof (not inferred from symptoms)

Inspected the embedded font's `ToUnicode` CMap directly with `pikepdf`:

```
font: /9 = AAAAAB+Tahoma (TrueType, subsetted)
codespace range: <20> to <92>   (115 glyph codes total)
```

Dumping every `bfrange`/`bfchar` entry in that CMap: **every single mapped
target is a Thai consonant, a leading vowel (เ/แ/โ/ใ/ไ — these are not
combining marks), a digit, or ASCII punctuation. Not one entry maps to any
Thai combining vowel or tone mark** (Unicode ranges U+0E31, U+0E34-E3A,
U+0E47-E4E). The font subset embedded in this PDF simply never had those
glyphs entered into its ToUnicode table when the file was generated
(most likely a subsetting bug in whatever produced this Crystal-Reports-style
export — it kept consonant/digit/punctuation glyphs but dropped combining
marks from the CMap).

**Cross-check that this is a CMap defect and not a missing/broken glyph
program**: rendering the *same* font at 300 DPI via PyMuPDF and reading the
pixels directly (screenshot below, cropped to the first row's Name cell)
shows the glyphs draw completely correctly — visually, the text reads
"มินิเค้กแฟนซี" with all vowels and tone marks present and correctly shaped:

```
rendered pixels -> OCR (tesseract tha+eng) -> "มินิเค้กแฟ นซี"
```

This proves the font's *glyph program* is intact; only the *ToUnicode
mapping used for text extraction* is incomplete. No amount of extraction-
side logic (reading order, normalization, table reconstruction) can recover
characters whose identity was never recorded in the content stream — the
data is not present to extract. This is exactly the scenario OCR fallback
exists for.

## Fix implemented

- `extract/text.py`: `_thai_combining_density()` — detects this class of
  defect directly (a Thai-heavy text run with near-zero combining-mark
  density is almost certainly missing glyphs, not just noisy), feeding into
  the existing `TextQuality.reliable` signal.
- `extract/ocr.py`: `OCRService` — renders the affected page at 300 DPI
  (PyMuPDF) and runs region-scoped Tesseract OCR (`tha+eng`) on just the
  bounding box of the affected field, not the whole page.
- `validate/cross_validate.py`: `ThaiOcrCrossValidator` — runs OCR only for
  string-typed fields containing Thai text on pages already flagged
  text-layer-unreliable; never touches code/numeric fields. Below
  `ocr_confidence_medium` the OCR result is discarded and the field stays
  on the (known-bad) PDF text, correctly flagged rather than replaced with
  a guess. At or above that threshold, OCR's reading replaces the value,
  with `raw_value` (PDF) and `ocr_raw_value` (OCR) both preserved
  side-by-side for audit — neither is ever overwritten.

## Result on the golden sample

| Metric | Before OCR | After OCR |
|---|---|---|
| `name` fields with a legible reading | 0 / 154 | 115 / 154 (74.7%) |
| Mean `name` field confidence | 0.40 (flat) | 0.77 |
| `name` fields still needing manual review | 154 / 154 | 154 / 154 (unchanged — see below) |
| Document status | REVIEW_RECOMMENDED (95.9%) | REVIEW_RECOMMENDED (98.0%) |
| Non-Thai fields (barcode/weight/PU/SKU/DN/DO/Order/etc.) | 100% match to source | 100% match to source (no regression) |
| Department reconciliation | 9/9 passed, 0 errors | 9/9 passed, 0 errors |

**Every `name` field still stays `review_required=True`.** This is
intentional, not a shortfall: this document mixes Thai product names with
Latin SKU-line prefixes (`SU`, `WRF_`, `OUM`, ...), and Tesseract's combined
`tha+eng` model frequently misreads those Latin prefixes as stray Thai
glyphs even when it reads the Thai portion correctly (e.g. `SU ช็อกโกแลต...`
comes back as `รป ช็อกโกแลต...`). None of the 154 rows reached the
`ocr_confidence_high` (0.95) bar this sample's mixed-script text needs to be
auto-cleared — which is the correct outcome per "ไม่แน่ใจ = ห้ามเดา": OCR
materially improves what a human reviewer sees (a legible candidate reading
next to the raw PDF text, instead of pure noise), but does not fabricate
certainty that isn't there.

## Known limitations / what OCR does not fix

- Mixed Thai/English SKU-prefix tokens (`SU`, `WRF_`, `OUM`, `SM`, ...) are
  the main remaining error source — a Thai-specialized OCR engine (e.g.
  PaddleOCR's Thai model) or a two-pass OCR (English-only pass for the
  prefix, Thai-only pass for the rest) would likely do better here; not
  implemented in this slice.
- 39/154 fields had OCR confidence below the medium threshold and were left
  on the (known-incomplete) PDF text, correctly flagged — these need a
  human to read the PDF directly via the review UI's embedded viewer.
- OCR adds real per-document latency (~60s for this 11-page/154-row
  document, all region calls). Acceptable for this vertical slice's
  correctness-over-speed priority; page-parallel processing (proposal §50)
  is still deferred and would help here.
