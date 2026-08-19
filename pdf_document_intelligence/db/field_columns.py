"""Single source of truth for which `product_rows` column backs each
editable field name - shared by the review API (writing corrections) and
the repository (reverting them on undo) so the two can never drift apart.
"""
from __future__ import annotations

FIELD_TO_COLUMN = {
    "name": "resolved_product_name",
    "weight_qty": "weight_qty",
    "pu_qty": "pu_qty",
    "sku_qty": "sku_qty",
    "unit_price": "unit_price",
    "amount": "amount",
    "unit": "unit",
    "department": "department",
    "barcode": "barcode",
    "article": "article_code",
}

NUMERIC_FIELDS = {"weight_qty", "pu_qty", "sku_qty", "unit_price", "amount"}
