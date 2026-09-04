"""User request (Loss Prevention watch-list): a Dashboard card surfacing
only "focus items" - rows worth a reviewer's attention out of possibly
thousands - so LP staff don't have to scan the full Products table by
hand every day.

Criteria are the user's own explicit spec, as updated by two 2026-09
follow-up requests:
- department == "LIQUOR", or product name containing เหล้า/เบียร์/วิสกี้/ไวน์
- product name containing นมผง or "milk powder"
- department == "MAJOR APPLIANCE", or product name containing
  ตู้เย็น/ทีวี/เครื่องซักผ้า ("แอร์" was removed - false-matched non-
  appliance products like an air-freshener spray branded "แอร์เอ็กซ์")
- sku_qty >= 100 pieces AND amount > 5,000 baht, both on the same row -
  a big-lot row is only flagged if it's also actually worth something;
  qty alone is no longer enough
- the standalone "amount >= 1,000 baht" rule was removed entirely - too
  noisy flagging every moderately-priced single-unit row
- ANY of the above (other than the two-part big-lot rule, which needs
  both its own parts) is enough to flag a row on its own.

focusItemReasons() is a pure function (no DOM/imports) - executed
directly via Node for real behavioral coverage, matching this project's
established pattern (see test_dashboard_reconciliation_warning.py).
Verified live in a browser (Playwright) against the real app: a synthetic
LIQUOR row with sku_qty=150 was correctly flagged with both "liquor" and
"bigLot" reasons, rendered in the card, and opened the product detail
panel on click.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "frontend" / "app" / "views" / "dashboard.js"

NODE = shutil.which("node")


def _extract_function(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    paren_start = source.index("(", start)
    paren_depth = 0
    i = paren_start
    while True:
        if source[i] == "(":
            paren_depth += 1
        elif source[i] == ")":
            paren_depth -= 1
            if paren_depth == 0:
                break
        i += 1
    brace_start = source.index("{", i)
    depth = 0
    i = brace_start
    while True:
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
        i += 1


def _extract_const(source: str, name: str) -> str:
    start = source.index(f"const {name} =")
    end = source.index(";", start)
    return source[start : end + 1]


def _run(product):
    source = DASHBOARD.read_text(encoding="utf-8")
    consts = "\n".join(
        _extract_const(source, name)
        for name in [
            "FOCUS_LIQUOR_DEPARTMENT",
            "FOCUS_LARGE_APPLIANCE_DEPARTMENT",
            "FOCUS_NAME_KEYWORDS",
            "FOCUS_QTY_THRESHOLD",
            "FOCUS_BIG_LOT_AMOUNT_THRESHOLD",
        ]
    )
    helper = _extract_function(source, "_nameHasAnyKeyword")
    fn = _extract_function(source, "focusItemReasons")
    script = f"""
{consts}
{helper}
{fn}
const product = {json.dumps(product)};
console.log(JSON.stringify(focusItemReasons(product)));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _product(*, department=None, name=None, amount=None, sku_qty=None):
    return {
        "department": department,
        "fields": {
            "name": {"value": name},
            "amount": {"value": amount},
            "sku_qty": {"value": sku_qty},
        },
    }


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_liquor_department_is_flagged():
    reasons = _run(_product(department="LIQUOR", name="ANYTHING"))
    assert "liquor" in reasons


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_liquor_keyword_in_name_is_flagged_even_outside_the_liquor_department():
    reasons = _run(_product(department="BEVERAGE", name="เบียร์สิงห์ 320ml"))
    assert "liquor" in reasons


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_milk_powder_keyword_matches_thai_and_english():
    assert "milkPowder" in _run(_product(name="นมผงตราหมี"))
    assert "milkPowder" in _run(_product(name="Milk Powder Brand X"))


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_large_appliance_keywords_are_flagged():
    for word in ["ตู้เย็น", "ทีวี", "เครื่องซักผ้า"]:
        assert "largeAppliance" in _run(_product(name=f"สินค้า {word} รุ่นใหม่"))


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_air_substring_in_a_product_name_no_longer_false_matches_large_appliance():
    # User report (live screenshot): "แอร์" as a keyword matched any name
    # containing that substring, including non-appliance products like an
    # air-freshener spray branded "แอร์เอ็กซ์" - removed from the keyword
    # list entirely. Real air conditioners are still caught via the
    # MAJOR APPLIANCE department rule, not by name.
    reasons = _run(_product(department="OVER THE COUNTER", name="P_ แอร์ เอ็กซ์ ดรอป 15 มล"))
    assert "largeAppliance" not in reasons


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_major_appliance_department_is_flagged_even_without_a_matching_name():
    reasons = _run(_product(department="MAJOR APPLIANCE", name="ANYTHING"))
    assert "largeAppliance" in reasons


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_standalone_high_amount_rule_was_removed():
    # User request: a moderately-priced single-unit row must not be
    # flagged on value alone anymore - only bigLot (qty + amount together)
    # or a category match can flag a row now.
    reasons = _run(_product(department="BAKERY", name="ธรรมดา", amount=50000))
    assert reasons == []


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_big_lot_requires_both_quantity_and_amount_thresholds_on_the_same_row():
    # qty >= 100 alone is no longer enough - amount must also exceed 5,000
    # (follow-up request); each threshold missing on its own must not flag.
    assert "bigLot" not in _run(_product(name="ธรรมดา", sku_qty=150, amount=5000))
    assert "bigLot" not in _run(_product(name="ธรรมดา", sku_qty=99, amount=6000))
    assert "bigLot" not in _run(_product(name="ธรรมดา", sku_qty=100))
    assert "bigLot" in _run(_product(name="ธรรมดา", sku_qty=100, amount=5000.01))


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_an_ordinary_row_matches_nothing():
    reasons = _run(_product(department="BAKERY", name="ขนมปัง A", amount=50, sku_qty=4))
    assert reasons == []


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_a_row_can_match_multiple_reasons_at_once():
    reasons = _run(_product(department="LIQUOR", name="วิสกี้พรีเมียม", amount=6000, sku_qty=200))
    assert set(reasons) == {"liquor", "bigLot"}


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_missing_name_and_numeric_fields_do_not_crash():
    reasons = _run(_product(department="BAKERY"))
    assert reasons == []


def _run_grouped(products):
    """groupFocusItemsByBarcode() - user request: the Focus Items card must
    combine multiple rows sharing the same barcode into one card (summed
    qty/amount, merged reasons) instead of listing them separately."""
    source = DASHBOARD.read_text(encoding="utf-8")
    consts = "\n".join(
        _extract_const(source, name)
        for name in [
            "FOCUS_LIQUOR_DEPARTMENT",
            "FOCUS_LARGE_APPLIANCE_DEPARTMENT",
            "FOCUS_NAME_KEYWORDS",
            "FOCUS_QTY_THRESHOLD",
            "FOCUS_BIG_LOT_AMOUNT_THRESHOLD",
        ]
    )
    helper = _extract_function(source, "_nameHasAnyKeyword")
    reasons_fn = _extract_function(source, "focusItemReasons")
    group_fn = _extract_function(source, "groupFocusItemsByBarcode")
    script = f"""
{consts}
{helper}
{reasons_fn}
{group_fn}
const products = {json.dumps(products)};
const focusRows = products.map((product, i) => ({{ product: {{ ...product, rowId: product.rowId || `row-${{i}}` }}, reasons: focusItemReasons(product) }}));
const groups = groupFocusItemsByBarcode(focusRows);
console.log(JSON.stringify(groups.map((g) => ({{
  barcode: g.barcode, name: g.name, department: g.department, reasons: g.reasons,
  qty: g.qty, amount: g.amount, amountAvailable: g.amountAvailable, rowCount: g.rows.length,
}}))));
"""
    result = subprocess.run([NODE, "-e", script], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _product_with_barcode(barcode, *, rowId=None, department=None, name=None, amount=None, sku_qty=None):
    p = _product(department=department, name=name, amount=amount, sku_qty=sku_qty)
    p["fields"]["barcode"] = {"value": barcode}
    if rowId:
        p["rowId"] = rowId
    return p


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_rows_sharing_a_barcode_are_combined_into_one_group_with_summed_totals():
    groups = _run_grouped([
        _product_with_barcode("111", rowId="r1", department="LIQUOR", name="เบียร์สิงห์", amount=600, sku_qty=50),
        _product_with_barcode("111", rowId="r2", department="LIQUOR", name="เบียร์สิงห์", amount=700, sku_qty=80),
    ])
    assert len(groups) == 1
    g = groups[0]
    assert g["barcode"] == "111"
    assert g["rowCount"] == 2
    assert g["qty"] == 130
    assert g["amount"] == 1300
    assert g["amountAvailable"] is True


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_reasons_from_every_contributing_row_are_merged_not_just_the_first():
    groups = _run_grouped([
        _product_with_barcode("222", rowId="r1", department="BAKERY", name="นมผงตรา A"),
        _product_with_barcode("222", rowId="r2", department="BAKERY", name="ธรรมดา", sku_qty=150, amount=6000),
    ])
    assert len(groups) == 1
    assert set(groups[0]["reasons"]) == {"milkPowder", "bigLot"}


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_different_barcodes_stay_in_separate_groups():
    groups = _run_grouped([
        _product_with_barcode("111", rowId="r1", department="LIQUOR", name="เบียร์"),
        _product_with_barcode("222", rowId="r2", department="LIQUOR", name="ไวน์"),
    ])
    assert len(groups) == 2
    assert {g["barcode"] for g in groups} == {"111", "222"}


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_rows_with_no_barcode_at_all_are_never_merged_together():
    groups = _run_grouped([
        _product(department="LIQUOR", name="เบียร์ไม่ทราบรหัส A", amount=2000),
        _product(department="LIQUOR", name="เบียร์ไม่ทราบรหัส B", amount=3000),
    ])
    assert len(groups) == 2
    assert all(g["barcode"] is None for g in groups)
