"""Template profile for the Big C CDC "Packing List" document type
(fingerprint: page header carries "Packing List" title + "Consignee :" +
"Route :" + a "Department :" section with the canonical column header
below). This is the golden-sample-derived template (proposal §38); a real
system would have many of these, matched via TemplateMatcher/fingerprint
(§41) — this one is hand-registered as the first template while that
matching engine doesn't exist yet.

Header tokens are matched in order, case-sensitive, against consecutive
words on the same text line. Multi-word headers (e.g. "Order no.") are
listed as multiple tokens that must appear consecutively.
"""
from __future__ import annotations

from dataclasses import dataclass

TEMPLATE_ID = "packing_list_bigc_cdc"
TEMPLATE_VERSION = "v1"


@dataclass(frozen=True)
class ColumnSpec:
    canonical_name: str
    header_tokens: tuple[str, ...]
    field_type: str  # FieldType from models.document
    is_group_key: bool = False  # forward-filled: blank cell inherits previous row's value
    required: bool = True  # blank is legitimate (not MISSING_FIELD) when False


COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("dn_no", ("DN", "no"), "code", is_group_key=True),
    ColumnSpec("do_no", ("DO",), "code", is_group_key=True),
    ColumnSpec("order_no", ("Order", "no."), "code", is_group_key=True),
    ColumnSpec("line", ("Line",), "integer"),
    ColumnSpec("pallet", ("Pallet",), "code", is_group_key=True),
    ColumnSpec("lot", ("Lot",), "code"),
    ColumnSpec("article", ("Article",), "code"),
    ColumnSpec("barcode", ("Barcode",), "code"),
    ColumnSpec("name", ("Name",), "string"),
    ColumnSpec("weight_qty", ("Weight", "qty"), "decimal"),
    ColumnSpec("pu_qty", ("PU", "qty"), "integer"),
    ColumnSpec("sku_qty", ("SKU", "qty"), "integer"),
    ColumnSpec("remarks", ("REMARKS",), "string", required=False),
)

RECONCILIATION_COLUMNS = ("weight_qty", "pu_qty", "sku_qty")

REQUIRED_HEADER_FIRST_TOKEN = "DN"
DEPARTMENT_LABEL = "Department"
TOTAL_LABEL = "Total"
