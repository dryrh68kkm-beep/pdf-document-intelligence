"""Template profile for the BPDC "Packing List" document type (fingerprint:
same Consignee/Route header block as packing_list_bigc, but "Department"
is an inline, forward-filled table column instead of a per-page heading,
and rows are grouped by a "Pallet no. : X   Lot no. : Y" line instead of a
per-page department section — one pallet can carry several departments'
worth of rows.

Confirmed the primary/most common document type as of the second sample
provided (23 pages, ~110 pallet blocks) — packing_list_bigc.py remains
registered for documents that still use the older per-page-department
layout.
"""
from __future__ import annotations

from pdf_document_intelligence.templates.base import ColumnSpec

TEMPLATE_ID = "packing_list_bpdc"
TEMPLATE_VERSION = "v1"

COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("dn_no", ("DN", "no"), "code", is_group_key=True),
    ColumnSpec("do_no", ("DO",), "code", is_group_key=True),
    ColumnSpec("order_no", ("Order", "no."), "code", is_group_key=True),
    ColumnSpec("line", ("Line",), "integer"),
    ColumnSpec("department", ("Department",), "string", is_group_key=True),
    ColumnSpec("article", ("Article",), "code"),
    ColumnSpec("barcode", ("Barcode",), "code"),
    ColumnSpec("name", ("Name",), "string"),
    ColumnSpec("weight_qty", ("Weight",), "decimal"),
    ColumnSpec("pu_qty", ("PU", "qty"), "integer"),
    ColumnSpec("sku_qty", ("SKU", "qty"), "integer"),
    ColumnSpec("remarks", ("Remark",), "string", required=False),
)

RECONCILIATION_COLUMNS = ("weight_qty", "pu_qty", "sku_qty")

REQUIRED_HEADER_FIRST_TOKEN = "DN"
PALLET_LABEL = "Pallet"
LOT_LABEL = "Lot"
TOTAL_LABEL = "Total"

# FOC = "free of charge" in this document's own Remark column. Checked
# against the real sample and NOT used as a non-product signal: FOC rows
# are ordinary sellable products (Coke, Singha/Chang beer, MSG seasoning)
# on an unbilled shipment - a billing attribute, not evidence the item
# isn't real inventory. Kept as a recognized value for the Remark field's
# own display/audit trail, not for classification.
FOC_REMARK = "FOC"
