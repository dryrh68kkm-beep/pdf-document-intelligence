"""Builds frontend/review.html: a self-contained (no server, no build step)
review UI for one processed document, by running the pipeline and inlining
its JSON result + the source PDF (base64) into frontend/review_template.html.

Usage: python scripts/build_review_html.py <path-to-pdf> [output.html]
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf_document_intelligence.pipeline.orchestrator import process_document

TEMPLATE = Path(__file__).parent.parent / "frontend" / "review_template.html"


def build_review_data(pdf_path: Path) -> dict:
    result = process_document(pdf_path)
    data = {
        "filename": result.filename,
        "pages": result.pages,
        "documentType": result.document_type,
        "templateVersion": result.template_version,
        "engineVersion": result.engine_version,
        "confidence": round(result.confidence, 2),
        "status": result.status,
        "reconciled": result.validation.reconciled,
        "errors": len(result.validation.errors),
        "warnings": len(result.validation.warnings),
        "departments": [],
    }

    def field_view(fv):
        return {
            "value": fv.value,
            "raw": fv.raw_value,
            "confidence": round(fv.confidence, 2),
            "review": fv.review_required,
            "flags": fv.validation_flags,
            "page": fv.bbox.page,
        }

    for table in result.tables:
        dept = {
            "name": table.name,
            "pageStart": table.page_start,
            "pageEnd": table.page_end,
            "rowCount": len(table.rows),
            "rows": [],
        }
        for row in table.rows:
            f = row.fields
            dept["rows"].append(
                {
                    "idx": row.row_index,
                    "band": row.confidence_band,
                    **{name: field_view(f[name]) for name in f},
                }
            )
        data["departments"].append(dept)
    return data


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(1)
    pdf_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent.parent / "frontend" / "review.html"

    data = build_review_data(pdf_path)
    data_json = json.dumps(data, ensure_ascii=False)
    pdf_b64 = base64.b64encode(pdf_path.read_bytes()).decode("ascii")

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__DATA_JSON__", data_json).replace("__PDF_BASE64__", pdf_b64)
    out_path.write_text(html, encoding="utf-8")
    print(f"Wrote {out_path} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
