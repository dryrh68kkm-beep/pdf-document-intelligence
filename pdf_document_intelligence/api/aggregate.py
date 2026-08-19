"""Cross-document dashboard aggregation.

Aggregates only over numeric fields that actually exist in the extracted
schema (weight_qty/pu_qty/sku_qty for this document type) — never
fabricates a price/amount total that isn't backed by extracted evidence.
Department identity is the department name; product identity within a
department is the `article` code (falls back to `barcode` when article is
missing), matching how the source documents identify a line item.
"""
from __future__ import annotations

from collections import defaultdict

from pdf_document_intelligence.api.store import DocumentEntry
from pdf_document_intelligence.templates.packing_list_bigc import RECONCILIATION_COLUMNS

# Only the columns the document itself reconciles against a printed total
# (proposal §27) are meaningful KPI/department totals — a running "Line"
# sequence number is typed integer too but summing it would be meaningless.
NUMERIC_COLUMNS = list(RECONCILIATION_COLUMNS)
NUMERIC_LABELS = {"weight_qty": "น้ำหนักรวม (กก.)", "pu_qty": "PU รวม", "sku_qty": "SKU qty รวม"}


def _identity(fields: dict) -> str | None:
    article = fields.get("article")
    if article and article.value:
        return str(article.value)
    barcode = fields.get("barcode")
    if barcode and barcode.value:
        return str(barcode.value)
    return None


def build_dashboard_state(docs: list[DocumentEntry]) -> dict:
    completed = [d for d in docs if d.status == "complete" and d.result]

    dept_skus: dict[str, set[str]] = defaultdict(set)
    dept_totals: dict[str, dict[str, float]] = defaultdict(lambda: {c: 0.0 for c in NUMERIC_COLUMNS})
    dept_review: dict[str, int] = defaultdict(int)
    dept_rows: dict[str, int] = defaultdict(int)
    dept_non_product: dict[str, int] = defaultdict(int)
    grand_totals: dict[str, float] = {c: 0.0 for c in NUMERIC_COLUMNS}
    review_items: list[dict] = []
    non_product_items: list[dict] = []
    total_rows = 0

    for doc in completed:
        for table in doc.result.tables:
            for row in table.rows:
                total_rows += 1
                name_field = row.fields.get("name")

                # Suspected non-product rows (proposal-adjacent: internal
                # POP/marketing-material items or explicit free-gift
                # descriptions, per catalog/classify.py) are tracked
                # separately - excluded from the ordinary SKU/quantity
                # totals rather than silently counted as inventory.
                if row.suspected_non_product:
                    dept_non_product[table.name] += 1
                    non_product_items.append(
                        {
                            "rowId": f"{doc.id}:{table.name}:{row.row_index}",
                            "docId": doc.id,
                            "docFilename": doc.filename,
                            "department": table.name,
                            "name": name_field.value if name_field else None,
                            "reasons": row.non_product_reasons,
                            "page": name_field.bbox.page if name_field else table.page_start,
                        }
                    )
                    continue

                dept_rows[table.name] += 1
                identity = _identity(row.fields)
                if identity:
                    dept_skus[table.name].add(identity)
                review_required = any(fv.review_required for fv in row.fields.values())
                if review_required:
                    dept_review[table.name] += 1
                    review_items.append(
                        {
                            "rowId": f"{doc.id}:{table.name}:{row.row_index}",
                            "docId": doc.id,
                            "docFilename": doc.filename,
                            "department": table.name,
                            "name": name_field.value if name_field else None,
                            "band": row.confidence_band,
                            "flags": sorted({f for fv in row.fields.values() for f in fv.validation_flags}),
                            "page": name_field.bbox.page if name_field else table.page_start,
                        }
                    )
                for col in NUMERIC_COLUMNS:
                    fv = row.fields.get(col)
                    if fv and isinstance(fv.value, (int, float)):
                        dept_totals[table.name][col] += fv.value
                        grand_totals[col] += fv.value

    all_dept_names = set(dept_rows) | set(dept_non_product)
    departments = [
        {
            "name": name,
            "skuCount": len(dept_skus[name]),
            "rowCount": dept_rows[name],
            "reviewCount": dept_review[name],
            "nonProductCount": dept_non_product[name],
            "totals": {c: round(v, 3) for c, v in dept_totals[name].items()},
        }
        for name in all_dept_names
    ]
    departments.sort(key=lambda d: d["totals"].get("sku_qty", 0), reverse=True)

    return {
        "documentCount": len(docs),
        "completedCount": len(completed),
        "processingCount": sum(1 for d in docs if d.status == "processing"),
        "errorCount": sum(1 for d in docs if d.status == "error"),
        "departmentCount": len(departments),
        "skuCount": len({s for skus in dept_skus.values() for s in skus}),
        "rowCount": total_rows,
        "reviewCount": len(review_items),
        "nonProductCount": len(non_product_items),
        "numericColumns": [{"key": c, "label": NUMERIC_LABELS.get(c, c)} for c in NUMERIC_COLUMNS],
        "grandTotals": {c: round(v, 3) for c, v in grand_totals.items()},
        "departments": departments,
        "reviewItems": review_items,
        "nonProductItems": non_product_items,
    }
