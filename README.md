# pdf-document-intelligence

Accuracy-first PDF document intelligence pipeline: PDF in, structured
department/product data out, with full evidence back to the source
document for every value. See `docs/APPLICATION.md` for the current
application architecture and `docs/OCR_ROOT_CAUSE.md` for a worked
example of the evidence-first approach applied to a real corrupted PDF.

## Running the desktop web application

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,ocr,dev]"

# System OCR engine (not a Python package):
sudo apt-get install -y tesseract-ocr tesseract-ocr-tha

uvicorn pdf_document_intelligence.api.app:app --reload
```

Open http://127.0.0.1:8000/ — a single-page app: add PDFs via the bottom
bar or drag-and-drop anywhere, watch them process automatically, and
browse the resulting Dashboard / Departments / Products / Review /
Documents views without a page reload. See `docs/APPLICATION.md` for the
application architecture and what's implemented vs. deferred.

## Running tests

```bash
pytest
```

The golden regression tests (`tests/integration/test_golden_regression*.py`)
run the full pipeline including real Tesseract OCR against sample
documents and take a few minutes (~4-5 minutes for the full suite,
measured) - `.github/workflows/tests.yml` splits these into their own CI
job for that reason, separate from the fast unit/API tests.
