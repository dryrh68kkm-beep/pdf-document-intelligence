from pdf_document_intelligence.catalog.classify import classify_product


def test_paq_prefix_flags_internal_marketing_material():
    result = classify_product("PAQ1_MKT_HPBIGSTANDEECLEARANCE")
    assert result.suspected_non_product is True
    assert "PAQ_INTERNAL_PREFIX" in result.reasons


def test_explicit_free_gift_phrase_flags():
    result = classify_product("CATCHA ชุดของแถมรองเท้า CXLYKN")
    assert result.suspected_non_product is True


def test_real_product_with_label_in_name_is_not_flagged():
    """Regression guard: an earlier draft used loose substring keywords
    (POP/LABEL/STAND/TAG) and mis-flagged real, sellable products - kept
    here as the specific cases that proved the loose approach wrong."""
    assert classify_product("JOHNNIE WALKER GOLD LABEL 70 CL(M)").suspected_non_product is False
    assert classify_product("POPTEENนร.หญิงPVCดำ PG44 S26").suspected_non_product is False
    assert classify_product("แปรงสีฟันซิสเทมมาXL STANDARD(P)").suspected_non_product is False


def test_real_product_with_promo_pricing_is_not_flagged():
    """A discounted real product ('promotional price') is still a
    product, not a giveaway - this exact case was caught by an earlier
    draft's "ราคาโปรโมชั่น" keyword and removed."""
    assert classify_product("เครื่องใน ราคาโปรโมชั่น").suspected_non_product is False


def test_real_product_with_hanging_tag_in_name_is_not_flagged():
    """A luggage tag sold as a travel accessory is a real product - this
    exact case was caught by an earlier draft's "ป้ายห้อย" keyword and
    removed."""
    assert classify_product("TRI ป้ายห้อยกระเป๋าเดินทาง").suspected_non_product is False


def test_empty_name_is_not_flagged():
    result = classify_product(None)
    assert result.suspected_non_product is False
    assert result.reasons == []
