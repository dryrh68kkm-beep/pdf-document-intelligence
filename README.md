# pdf-document-intelligence

Accuracy-first PDF document intelligence pipeline: PDF in, structured
department/product data out, with full evidence back to the source
document for every value. See `docs/ARCHITECTURE_PROPOSAL.md` for the
full design rationale and `docs/OCR_ROOT_CAUSE.md` for a worked example of
the evidence-first approach applied to a real corrupted PDF.

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

The golden regression test (`tests/integration/test_golden_regression.py`)
runs the full pipeline including OCR against a real sample document and
takes about a minute.
