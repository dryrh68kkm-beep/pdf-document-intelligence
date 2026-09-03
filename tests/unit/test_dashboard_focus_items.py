"""User request (Loss Prevention watch-list): a Dashboard card surfacing
only "focus items" - rows worth a reviewer's attention out of possibly
thousands - so LP staff don't have to scan the full Products table by
hand every day.

Criteria are the user's own explicit spec (2026-09 request):
- department == "LIQUOR", or product name containing เหล้า/เบียร์/วิสกี้/ไวน์
- product name containing นมผง or "milk powder"
- product name containing ตู้เย็น/ทีวี/แอร์/เครื่องซักผ้า
- amount >= 1,000 baht (per row)
- sku_qty >= 100 pieces (per row)
- ANY of the above is enough to flag a row - not all of them.

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
        for name in ["FOCUS_LIQUOR_DEPARTMENT", "FOCUS_NAME_KEYWORDS", "FOCUS_AMOUNT_THRESHOLD", "FOCUS_QTY_THRESHOLD"]
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
    for word in ["ตู้เย็น", "ทีวี", "แอร์", "เครื่องซักผ้า"]:
        assert "largeAppliance" in _run(_product(name=f"สินค้า {word} รุ่นใหม่"))


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_high_amount_is_flagged_at_the_threshold():
    assert "highAmount" in _run(_product(name="ธรรมดา", amount=1000))
    assert "highAmount" not in _run(_product(name="ธรรมดา", amount=999.99))


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_big_lot_quantity_is_flagged_at_the_threshold():
    assert "bigLot" in _run(_product(name="ธรรมดา", sku_qty=100))
    assert "bigLot" not in _run(_product(name="ธรรมดา", sku_qty=99))


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_an_ordinary_row_matches_nothing():
    reasons = _run(_product(department="BAKERY", name="ขนมปัง A", amount=50, sku_qty=4))
    assert reasons == []


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_a_row_can_match_multiple_reasons_at_once():
    reasons = _run(_product(department="LIQUOR", name="วิสกี้พรีเมียม", amount=5000, sku_qty=200))
    assert set(reasons) == {"liquor", "highAmount", "bigLot"}


@pytest.mark.skipif(NODE is None, reason="node not available in this environment")
def test_missing_name_and_numeric_fields_do_not_crash():
    reasons = _run(_product(department="BAKERY"))
    assert reasons == []
