import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STORE_SUITE_DATA_DIR", str(tmp_path / "suite"))
    monkeypatch.setenv("PDF_INTELLIGENCE_DATA_DIR", str(tmp_path / "pdf"))
    from store_suite.app import app

    with TestClient(app) as c:
        yield c


CSV = "BAR_CODE,DESCRIPTION,STOCK_QTY,DAY_LEFT,SUB_DEPT_NAME,DIV,DEPT\n8859847102864,SIMPLUS พัดลม,5,3,FAN,1,2\n9999999999999,นมสด,2,-1,DAIRY,1,3\n"


def test_shell_and_modules_served(client):
    assert "Store Suite" in client.get("/").text
    for path, marker in (("/m/expiry/", "window.fetch"), ("/m/atlas/", "window.fetch"), ("/m/pdf/", "window.fetch")):
        r = client.get(path)
        assert r.status_code == 200 and marker in r.text, path
    assert client.get("/m/pdf/styles.css").status_code == 200
    assert client.get("/m/pdf/api/health").status_code == 200


def test_atlas_api_state_roundtrip_and_conflict(client):
    assert client.get("/m/atlas/api/info").json()["server"] == "stock-atlas"
    assert client.get("/m/atlas/api/state/oos").status_code == 204
    body = json.dumps({"items": [{"barcode": "8859847102864", "name": "x", "soh": 0}]})
    r = client.put("/m/atlas/api/state/oos", content=body, headers={"X-If-Rev": "0"})
    assert r.status_code == 200
    rev = r.json()["rev"]
    assert client.get("/m/atlas/api/state/oos", headers={"X-If-Rev": rev}).status_code == 304
    assert client.put("/m/atlas/api/state/oos", content=body, headers={"X-If-Rev": "0"}).status_code == 409
    assert client.put("/m/atlas/api/state/oos", content="{}", headers={"X-If-Rev": rev}).status_code == 400
    assert client.put("/m/atlas/api/export/homes.csv", content="a,b").status_code == 200
    assert client.get("/m/atlas/export/homes.csv").text == "a,b"
    assert client.put("/m/atlas/api/inbox/../x.csv", content="a").status_code in (400, 404, 405)


def test_expiry_upload_sync_and_cross_lookup(client):
    r = client.post("/api/suite/expiry/upload", files={"file": ("NEARLY_EXPIRED_1003.csv", CSV.encode("utf-8"))})
    assert r.status_code == 200 and r.json()["rows"] == 2
    assert client.get("/m/expiry/data.csv").status_code == 200
    assert client.get("/m/expiry/status.json").json()["success"] is True
    # bad file never replaces good data
    bad = client.post("/api/suite/expiry/upload", files={"file": ("x.csv", b"A,B\n1,2\n")})
    assert bad.status_code == 422
    assert client.get("/m/expiry/data.csv").text.startswith("BAR_CODE")

    # Atlas OOS state + bundled count data are joined on the barcode
    oos = json.dumps({"items": [{"barcode": "8859847102864", "name": "พัดลม", "soh": 0}]})
    client.put("/m/atlas/api/state/oos", content=oos, headers={"X-If-Rev": "*"})
    p = client.get("/api/suite/product/8859847102864").json()
    assert p["expiry"][0]["daysLeft"] == 3
    assert p["homes"], "bundled Atlas count data should give this barcode a home"
    assert p["oos"] == {"soh": 0, "checked": False, "result": None}

    locs = client.get("/api/suite/expiry-locations?maxDays=30").json()
    assert locs["total"] == 2 and locs["rows"][0]["daysLeft"] == -1
    ov = client.get("/api/suite/overview").json()
    assert ov["expiry"]["expired"] == 1 and ov["atlas"]["oosOpen"] == 1

    rep = client.post("/api/suite/sync").json()
    assert rep["ok"] is True
    exp = client.get("/m/atlas/export/expiry-locations.csv")
    assert exp.status_code == 200 and "8859847102864" in exp.text
    assert client.get("/api/suite/search?q=พัดลม").json()[0]["barcode"] == "8859847102864"


def test_fetch_from_network_folder(client, tmp_path):
    src = tmp_path / "share"
    src.mkdir()
    (src / "NEARLY_EXPIRED_1003.csv").write_text(CSV, encoding="utf-8")
    client.put("/api/suite/config", json={"expirySourceFolder": str(src)})
    rep = client.post("/api/suite/sync").json()
    assert rep["steps"][0]["ok"] and rep["steps"][0]["rows"] == 2
    again = client.post("/api/suite/sync").json()
    assert again["steps"][0].get("skipped") == "source unchanged"


def test_lan_only_blocks_public_ip(client):
    from starlette.testclient import TestClient as TC
    from store_suite.app import app

    c = TC(app, client=("8.8.8.8", 5000))
    assert c.get("/api/suite/health").status_code == 403


def test_settings_and_upload_are_server_pc_only(client):
    from starlette.testclient import TestClient as TC
    from store_suite.app import app

    lan = TC(app, client=("192.168.1.50", 5000))   # allowed to browse, not to change settings
    assert lan.get("/api/suite/overview").status_code == 200
    assert lan.put("/api/suite/config", json={"atlasSources": [{"path": "C:/"}]}).status_code == 403
    assert lan.post("/api/suite/expiry/upload", files={"file": ("a.csv", b"x")}).status_code == 403
    local = TC(app, client=("127.0.0.1", 5000))
    assert local.put("/api/suite/config", json={"autoSyncMinutes": 5}).status_code == 200


def test_path_traversal_is_rejected(client):
    assert client.get("/m/atlas/api/file?src=0&name=../config.json").status_code == 400
    assert client.put("/m/atlas/api/export/..%2Fx.csv", content="a").status_code in (400, 404)
    assert client.get("/m/expiry/..%2F..%2Fconfig.json").status_code == 404
