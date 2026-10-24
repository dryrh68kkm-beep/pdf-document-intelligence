import json
from pathlib import Path

from store_suite import import_config

CONFIG_PS1 = '''\ufeff# comment
$SOURCE_FOLDER         = "\\\\10.1.2.3\\share\\data"     # network path
$SOURCE_FILE_BASENAME  = "NEARLY_EXPIRED_1003"
$SOURCE_FILE_EXTENSIONS = @('.csv', '.xlsx')
$LOCAL_DATA_PATH  = "%(www)s"
$APP_PORT   = 8090
$CLOUDFLARE_SYNC_ENABLED = $false
'''
CSV = "BAR_CODE,DESCRIPTION,STOCK_QTY,DAY_LEFT,SUB_DEPT_NAME,DIV,DEPT\n8859847102864,x,1,3,A,1,2\n"


def _make(tmp_path: Path):
    root = tmp_path / "LP-Tools"
    exp, atlas = root / "ExpiryApp", root / "Ooslayout"
    (exp / "www").mkdir(parents=True)
    (exp / "config.ps1").write_text(CONFIG_PS1 % {"www": str(exp / "www")}, encoding="utf-8")
    (exp / "fetch-data.ps1").write_text("# x", encoding="utf-8")
    (exp / "www" / "data.csv").write_text(CSV, encoding="utf-8")
    (atlas / "server").mkdir(parents=True)
    (atlas / "server" / "StockAtlasServer.ps1").write_text("# x", encoding="utf-8")
    (atlas / "server" / "config.json").write_text(json.dumps({
        "dataDir": "data",
        "sources": [{"name": "Inbox", "path": "data\\inbox"}, {"name": "POS drop", "path": "D:\\\\pos"}],
        "pog": [{"name": "POG", "path": "\\\\\\\\x\\\\pog"}],
    }), encoding="utf-8")
    (atlas / "data" / "state").mkdir(parents=True)
    (atlas / "data" / "state" / "oos.json").write_text(json.dumps({"items": [{"barcode": "1", "name": "n"}]}), encoding="utf-8")
    (atlas / "data" / "state" / "layout.json").write_text("not json", encoding="utf-8")
    return exp, atlas


def test_parse_config_ps1():
    v = import_config.parse_config_ps1(CONFIG_PS1 % {"www": "C:\\x"})
    assert v["SOURCE_FOLDER"] == "\\\\10.1.2.3\\share\\data" and v["SOURCE_FILE_EXTENSIONS"] == [".csv", ".xlsx"]
    assert v["APP_PORT"] == 8090 and v["CLOUDFLARE_SYNC_ENABLED"] is False


def test_scan_and_apply_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_SUITE_DATA_DIR", str(tmp_path / "suite"))
    exp, atlas = _make(tmp_path)
    monkeypatch.setattr(import_config, "APP_DIR", tmp_path / "LP-Tools" / "StoreSuite")  # not the real checkout's neighbours
    found = import_config.scan([str(tmp_path / "LP-Tools")])
    assert [e["path"] for e in found["expiry"]] == [str(exp.resolve())]
    assert found["atlas"][0]["atlasSources"] == [{"name": "POS drop", "path": "D:\\\\pos"}]   # default inbox skipped
    assert found["atlas"][0]["states"] == ["layout", "oos"]

    rep = import_config.apply(str(exp), str(atlas), [str(tmp_path / "LP-Tools")])
    assert rep["settings"]["expirySourceFolder"] == "\\\\10.1.2.3\\share\\data"
    assert {c["item"] for c in rep["copied"]} == {"expiry data", "atlas oos"}
    assert any(s["item"] == "atlas layout" for s in rep["skipped"])        # invalid file is not copied
    assert import_config.load_config()["atlasSources"][0]["path"] == "D:\\\\pos"

    # a second run copies nothing and changes nothing
    again = import_config.apply(str(exp), str(atlas), [str(tmp_path / "LP-Tools")])
    assert again["copied"] == [] and again["settings"] == {}


def test_apply_rejects_unknown_path(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_SUITE_DATA_DIR", str(tmp_path / "suite"))
    import pytest

    monkeypatch.setattr(import_config, "APP_DIR", tmp_path / "x" / "StoreSuite")
    with pytest.raises(ValueError):
        import_config.apply(str(tmp_path), None)
