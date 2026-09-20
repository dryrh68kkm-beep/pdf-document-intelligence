"""Windows installer must reject an English-only Tesseract install."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALL_BAT = ROOT / "install.bat"


def test_installer_requires_thai_tesseract_language_pack():
    source = INSTALL_BAT.read_text(encoding="utf-8")
    assert "tesseract --list-langs" in source
    assert 'findstr /R /X /C:"tha"' in source
    assert "Thai OCR language pack found" in source
    assert "Thai language pack is missing" in source


def test_installer_stays_plain_ascii():
    source = INSTALL_BAT.read_text(encoding="utf-8")
    assert all(ord(ch) < 128 for ch in source)
