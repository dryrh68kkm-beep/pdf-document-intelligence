from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.extract.text import field_has_thai_encoding_defect, score_text_quality


def test_clean_thai_text_is_reliable():
    settings = Settings()
    # Real Thai prose carries a healthy density of combining marks.
    text = "สวัสดีครับ ยินดีต้อนรับ เอกสารนี้ถูกต้องตามหลักภาษาไทยทุกประการครับ " * 3
    quality = score_text_quality(text, settings)
    assert quality.reliable is True


def test_thai_text_missing_combining_marks_is_flagged_unreliable():
    settings = Settings()
    # Simulates the real-world defect found in the golden sample: combining
    # vowels/tone marks silently dropped from the font's glyph map.
    text = "บมจบบกซซซเปอรซเซนเตอรซ ตตตบลไทรนอน อตตเภอไทรนอน สตขตไทรนอน " * 3
    quality = score_text_quality(text, settings)
    assert quality.thai_combining_density == 0.0
    assert quality.reliable is False


def test_short_non_thai_text_is_not_penalized_for_missing_thai_signal():
    settings = Settings()
    quality = score_text_quality("Packing List Page 1 of 11", settings)
    assert quality.thai_combining_density == -1.0  # not enough Thai chars to judge
    assert quality.reliable is True


def test_field_level_defect_detection_catches_garbled_short_name():
    """Real bug: a garbled product name cell ("เพอร์ริเย่ต์ น้ำแร่..." became
    "เพอรรรต่ นตนตแร...") is too short on its own to move a whole page's
    average score, but it's exactly the reordering defect
    _thai_valid_ratio/score_text_quality already know how to detect - this
    is the same check applied at field granularity."""
    settings = Settings()
    garbled = "เพอรรรต่ นตนตแร ่1500 มล.แพซค 6"
    assert field_has_thai_encoding_defect(garbled, settings.min_thai_valid_char_ratio) is True


def test_field_level_defect_detection_ignores_clean_name():
    settings = Settings()
    clean = "เพอร์ริเย่ต์ น้ำแร่ 1500 มล.แพ็ค 6"
    assert field_has_thai_encoding_defect(clean, settings.min_thai_valid_char_ratio) is False


def test_field_level_defect_detection_needs_at_least_two_combining_marks():
    settings = Settings()
    # A single combining mark is too little signal to act on for a short field.
    assert field_has_thai_encoding_defect("กัน", settings.min_thai_valid_char_ratio) is False
