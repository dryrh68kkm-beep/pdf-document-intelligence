from pdf_document_intelligence.config.settings import Settings
from pdf_document_intelligence.extract.text import score_text_quality


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
