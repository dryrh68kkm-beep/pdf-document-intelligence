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


def test_big_pages_are_gzipped_and_cached(client):
    r = client.get("/m/atlas/", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
    again = client.get("/m/atlas/", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_oos_and_expiry_are_kept_apart(client):
    client.post("/api/suite/expiry/upload", files={"file": ("a.csv", CSV.encode("utf-8"))})
    oos = json.dumps({"items": [{"barcode": "8859847102864", "name": "พัดลม", "soh": 0}, {"barcode": "111", "name": "ตรวจแล้ว", "soh": 2, "result": "FOUND"}]})
    client.put("/m/atlas/api/state/oos", content=oos, headers={"X-If-Rev": "*"})

    rows = client.get("/api/suite/expiry-locations?maxDays=9999").json()["rows"]
    assert rows and all("oos" not in r and "inPdf" not in r for r in rows)
    ov = client.get("/api/suite/overview").json()
    assert "links" not in ov

    pend = client.get("/api/suite/oos").json()
    assert [r["barcode"] for r in pend["rows"]] == ["8859847102864"] and pend["total"] == 1
    assert all("daysLeft" not in r and "homes" not in r for r in pend["rows"])
    assert client.get("/api/suite/oos?pending=false").json()["total"] == 2
    assert "source" in pend and "importedAt" in pend

    client.post("/api/suite/sync")
    csv_text = client.get("/m/atlas/export/expiry-locations.csv").text
    assert "OOS" not in csv_text.splitlines()[0]


def test_shutdown_is_server_pc_only(client):
    from starlette.testclient import TestClient as TC
    from store_suite.app import app

    assert TC(app, client=("192.168.1.50", 5000)).post("/api/suite/shutdown").status_code == 403


def test_server_side_filter_sort_and_paging(client):
    rows_csv = "BAR_CODE,DESCRIPTION,STOCK_QTY,DAY_LEFT,SUB_DEPT_NAME,DIV,DEPT\n" + "\n".join(
        f"88500000000{i:02d},สินค้า{i},{i},{i - 10},{'A' if i % 2 else 'B'},1,2" for i in range(30))
    client.post("/api/suite/expiry/upload", files={"file": ("a.csv", rows_csv.encode("utf-8"))})
    base = "/api/suite/expiry-locations?maxDays=9999"
    d = client.get(base + "&limit=10").json()
    assert d["total"] == 30 and len(d["rows"]) == 10 and d["rows"][0]["daysLeft"] == -10     # sorted by days left
    desc = client.get(base + "&sort=qty&dir=-1&limit=3").json()["rows"]
    assert [r["qty"] for r in desc] == [29, 28, 27]
    page2 = client.get(base + "&limit=10&offset=10").json()["rows"]
    assert page2[0]["daysLeft"] == 0 and page2[0]["barcode"] != d["rows"][0]["barcode"]
    assert client.get(base + "&dept=A").json()["total"] == 15
    assert client.get(base + "&q=" + "สินค้า7").json()["total"] >= 1

    items = [{"barcode": f"1{i:03d}", "name": f"ของ{i}", "soh": i - 5, **({"result": "FOUND"} if i % 3 == 0 else {})} for i in range(20)]
    client.put("/m/atlas/api/state/oos", content=json.dumps({"items": items}), headers={"X-If-Rev": "*"})
    assert client.get("/api/suite/oos?status=pending").json()["total"] == 13
    assert client.get("/api/suite/oos?status=all&soh=neg").json()["total"] == 5
    assert client.get("/api/suite/oos?status=all&soh=zero").json()["total"] == 1
    assert client.get("/api/suite/oos?status=done&sort=soh&dir=-1&limit=2").json()["rows"][0]["soh"] == 13
