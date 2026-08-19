"""Flattens a DocumentResult into the row-oriented JSON shape the SPA
consumes, and the field-level evidence needed by the detail/review panels.

Deliberately generic over which fields exist: this document type (a
packing list) has weight/PU/SKU quantities but no price/amount — the API
never fabricates a monetary figure that isn't in the extracted schema.
`numericColumns` tells the frontend which numeric fields this document
type actually has, so the UI adapts rather than assuming "amount" exists.
"""
from __future__ import annotations

from pdf_document_intelligence.api.store import DocumentEntry
from pdf_document_intelligence.models.document import FieldValue
from pdf_document_intelligence.templates.packing_list_bigc import RECONCILIATION_COLUMNS

NUMERIC_COLUMNS = list(RECONCILIATION_COLUMNS)
IDENTITY_COLUMN = "article"


def _field_json(fv: FieldValue) -> dict:
    return {
        "value": fv.value,
        "raw": fv.raw_value,
        "type": fv.type,
        "source": fv.source,
        "confidence": round(fv.confidence, 3),
        "review": fv.review_required,
        "flags": fv.validation_flags,
        "page": fv.bbox.page,
        "bbox": {"x": fv.bbox.x, "y": fv.bbox.y, "width": fv.bbox.width, "height": fv.bbox.height},
        "ocrRaw": fv.ocr_raw_value,
        "ocrConfidence": round(fv.ocr_confidence, 3) if fv.ocr_confidence is not None else None,
    }


def document_summary_json(doc: DocumentEntry) -> dict:
    base = {
        "id": doc.id,
        "filename": doc.filename,
        "status": doc.status,
        "uploadedAt": doc.uploaded_at.isoformat(),
        "progress": {
            "stage": doc.progress.stage,
            "current": doc.progress.current,
            "total": doc.progress.total,
        },
        "error": doc.error,
    }
    if doc.result:
        r = doc.result
        base.update(
            {
                "pages": r.pages,
                "confidence": round(r.confidence, 2),
                "status_document": r.status,
                "reconciled": r.validation.reconciled,
                "errors": len(r.validation.errors),
                "warnings": len(r.validation.warnings),
                "rowCount": sum(len(t.rows) for t in r.tables),
                "departmentCount": len(r.tables),
            }
        )
    return base


def document_detail_json(doc: DocumentEntry) -> dict:
    detail = document_summary_json(doc)
    if not doc.result:
        return detail
    r = doc.result
    detail["numericColumns"] = NUMERIC_COLUMNS
    detail["engineVersion"] = r.engine_version
    detail["ocrEngineVersion"] = r.ocr_engine_version
    detail["templateVersion"] = r.template_version
    detail["processingLog"] = [
        {"step": e.step, "detail": e.detail, "durationMs": round(e.duration_ms, 1) if e.duration_ms else None}
        for e in r.processing_log
    ]
    detail["validationIssues"] = [
        {
            "severity": i.severity,
            "code": i.code,
            "table": i.table,
            "rowIndex": i.row_index,
            "field": i.field,
            "message": i.message,
        }
        for i in [*r.validation.errors, *r.validation.warnings]
    ]

    products = []
    for table in r.tables:
        for row in table.rows:
            f = row.fields
            review_required = any(fv.review_required for fv in f.values())
            products.append(
                {
                    "rowId": f"{doc.id}:{table.name}:{row.row_index}",
                    "docId": doc.id,
                    "docFilename": doc.filename,
                    "department": table.name,
                    "page": f.get("name").bbox.page if f.get("name") else table.page_start,
                    "band": row.confidence_band,
                    "reviewRequired": review_required,
                    "suspectedNonProduct": row.suspected_non_product,
                    "nonProductReasons": row.non_product_reasons,
                    "fields": {name: _field_json(fv) for name, fv in f.items()},
                }
            )
    detail["products"] = products
    return detail


def all_products_json(docs: list[DocumentEntry]) -> list[dict]:
    products: list[dict] = []
    for doc in docs:
        if doc.status == "complete" and doc.result:
            products.extend(document_detail_json(doc)["products"])
    return products
