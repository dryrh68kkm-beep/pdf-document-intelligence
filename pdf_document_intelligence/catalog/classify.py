"""Conservative product-vs-non-product classification.

Per explicit decision (loose keyword matching was rejected after it
mis-caught real products — "POP" inside "POPTEEN", "LABEL" inside
"JOHNNIE WALKER GOLD LABEL", "STAND" inside toothbrush "STANDARD"):
this only flags on signals specific enough that a false positive on a
real product is implausible. It never deletes or silently reclassifies —
`classify_product` returns a flag + reasons; the row still carries its
full data, just tagged as a review-worthy candidate for the
"ของแถม / ไม่ใช่สินค้า" group instead of the ordinary product count.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Internal marketing-material barcode/name prefixes observed in the master
# catalog (e.g. "PAQ1_MKT_HPBIGSTANDEECLEARANCE", "PAQ1_POSM_STICKER_BB_REWARD",
# "PAQ1_ของแถมวิสกัส480G") - these are POP/display/premium item codes, not
# customer-facing product names.
_PAQ_PREFIX_RE = re.compile(r"^PAQ[12]_", re.IGNORECASE)

# Whole, specific phrases - not caught inside ordinary product names.
# "ป้ายห้อย" and "ราคาโปรโมชั่น" were tried and dropped: verified against
# the real catalog, both caught genuine sellable products ("TRI
# ป้ายห้อยกระเป๋าเดินทาง" is an actual luggage-tag product;
# "เครื่องใน ราคาโปรโมชั่น" is real meat at a promotional price, not a
# giveaway) - exactly the false-positive failure mode this module exists
# to avoid, so only "ของแถม" (a bundled free-gift description) remains.
_THAI_PHRASES = ("ของแถม",)
_LATIN_WORD_RE = re.compile(r"\b(POSM|STANDEE)\b", re.IGNORECASE)


@dataclass
class ProductClassification:
    suspected_non_product: bool
    reasons: list[str]


def classify_product(name: str | None) -> ProductClassification:
    """Note: this document's "Remark" column can carry "FOC" (free of
    charge). That was tried here as a non-product signal and reverted:
    checking the actual FOC rows in the BPDC sample (Coke cans, Singha/
    Chang beer, MSG seasoning) shows FOC marks a real product shipment
    the receiving store isn't billed for — a pricing/billing attribute,
    not evidence the line item isn't a real, sellable product. Using it
    here would have repeated the exact false-positive failure mode
    documented below for the loose keyword draft."""
    if not name:
        return ProductClassification(False, [])
    reasons: list[str] = []

    if _PAQ_PREFIX_RE.match(name.strip()):
        reasons.append("PAQ_INTERNAL_PREFIX")
    for phrase in _THAI_PHRASES:
        if phrase in name:
            reasons.append(f"KEYWORD:{phrase}")
    if _LATIN_WORD_RE.search(name):
        reasons.append("KEYWORD:POSM_OR_STANDEE")

    return ProductClassification(suspected_non_product=bool(reasons), reasons=reasons)
