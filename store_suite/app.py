"""Store Suite: one FastAPI process serving
  /            shell (tabs + overview + barcode search + sync button)
  /m/pdf/      PDF Document Intelligence (the original app, mounted as-is)
  /m/expiry/   Expiry Dashboard page + data.csv feed
  /m/atlas/    Stock Atlas page + its shared-state server API
  /api/suite/  the cross-program hub (overview, product lookup, sync, config)
"""
from __future__ import annotations

import asyncio
import json
import ipaddress
import logging
import os
import shutil
import threading
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from store_suite import __version__, atlas_api, expiry_data, import_config, shim
from store_suite.config import load_config, save_config
from store_suite.hub import Hub
from store_suite.paths import WEB_DIR, expiry_dir

# The PDF pipeline's reverse lookup reads the expiry feed from this folder;
# it must be set before the PDF app (and its Settings) is imported.
os.environ.setdefault("PDI_EXPIRY_DASHBOARD_WWW_DIR", str(expiry_dir()))
# ...and so must the Stock Atlas data it cross-checks barcodes/names against
# (shared count state if Atlas has saved one, else the count DB bundled with Atlas).
os.environ.setdefault(
    "PDI_CROSS_REFERENCE_COUNT_FILES",
    os.pathsep.join([str(atlas_api.state_file("count")), str(WEB_DIR / "modules" / "atlas" / "count-data.json")]),
)
os.environ.setdefault("PDI_CROSS_REFERENCE_POG_FILES", str(atlas_api.state_file("pog")))
os.environ.setdefault("PDI_CROSS_REFERENCE_OOS_FILES", str(atlas_api.state_file("oos")))

from pdf_document_intelligence.api import app as pdf_module  # noqa: E402

pdf_app = pdf_module.app
_logger = logging.getLogger("store_suite")

hub = Hub(pdf_products=pdf_module.list_all_products)


async def _auto_sync_loop() -> None:
    while True:
        minutes = load_config().get("autoSyncMinutes") or 0
        await asyncio.sleep(max(60, minutes * 60) if minutes else 60)
        if minutes:
            try:
                await asyncio.to_thread(hub.run_sync)
            except Exception:  # noqa: BLE001
                _logger.exception("auto sync failed")


@asynccontextmanager
async def _lifespan(_: FastAPI):
    # Mounted sub-apps do not get their own lifespan - run the PDF app's here
    # (recovers interrupted documents, starts the PDF inbox watcher).
    async with pdf_app.router.lifespan_context(pdf_app):
        task = asyncio.create_task(_auto_sync_loop())
        first_sync = asyncio.create_task(asyncio.to_thread(hub.run_sync))  # first sync at startup (kept referenced)
        try:
            yield
        finally:
            task.cancel()
            first_sync.cancel()


app = FastAPI(title="Store Suite", version=__version__, lifespan=_lifespan)
# The Atlas page is 7 MB of HTML: gzip makes it ~1.5 MB (matters on store Wi-Fi).
app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=5)


def _page(request: Request, name: str, path: Path) -> Response:
    """Shimmed module page with an ETag, so a repeat visit is a 304, not 7 MB."""
    etag = f'"{name}-{int(path.stat().st_mtime_ns)}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return HTMLResponse(shim.render(name, path), headers={"ETag": etag, "Cache-Control": "no-cache"})


def _is_lan(host: str | None) -> bool:
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # test client / unix socket
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip.is_private or ip.is_link_local


def _is_loopback(host: str | None) -> bool:
    if not host or host in ("localhost", "testclient"):  # "testclient": Starlette's TestClient, never a real peer
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback


def _require_local(request: Request) -> None:
    """Settings name folders this server will read files from, so only a
    browser on the server PC itself may change them - not any LAN device."""
    if not _is_loopback(request.client.host if request.client else None):
        raise HTTPException(403, "ตั้งค่าได้เฉพาะจากเครื่องที่รันโปรแกรมนี้")


@app.middleware("http")
async def lan_only(request: Request, call_next):
    if load_config().get("lanOnly") and not _is_lan(request.client.host if request.client else None):
        return JSONResponse({"error": "LAN only"}, status_code=403)
    return await call_next(request)


# ---------- hub API ----------
@app.get("/api/suite/overview")
def overview():
    return hub.overview()


@app.get("/api/suite/product/{barcode}")
def product(barcode: str):
    return hub.product(barcode)


@app.get("/api/suite/search")
def search(q: str = "", limit: int = 20):
    return hub.search(q, max(1, min(limit, 100)))


@app.get("/api/suite/expiry-locations")
def expiry_locations(maxDays: float | None = 30, limit: int = 500):
    rows = hub.expiry_locations(None if maxDays is not None and maxDays >= 9999 else maxDays)
    return {"total": len(rows), "rows": rows[: max(1, min(limit, 5000))]}


@app.get("/api/suite/oos")
def oos(pending: bool = True, limit: int = 1000):
    rows = hub.oos_items(pending)
    state = atlas_api.read_state("oos") or {}
    src = state.get("source")
    return {
        "total": len(rows),
        "rows": rows[: max(1, min(limit, 5000))],
        "source": src if isinstance(src, str) else json.dumps(src, ensure_ascii=False) if src else "",
        "importedAt": state.get("importedAt") or "",
    }


@app.post("/api/suite/shutdown")
async def shutdown(request: Request):
    """Close Store Suite (there is no console window to close). Server PC only."""
    _require_local(request)
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {"ok": True}


@app.post("/api/suite/sync")
async def sync():
    return await asyncio.to_thread(hub.run_sync)


@app.get("/api/suite/config")
def get_config():
    return load_config()


@app.put("/api/suite/config")
async def put_config(request: Request):
    _require_local(request)
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "config must be an object")
    return save_config(body)


@app.get("/api/suite/import/scan")
def import_scan(dirs: str = ""):
    """Look for the standalone programs next to this folder (read-only)."""
    return import_config.scan([d for d in dirs.split("|") if d])


@app.post("/api/suite/import/apply")
async def import_apply(request: Request):
    _require_local(request)
    body = await request.json()
    try:
        res = import_config.apply(body.get("expiry"), body.get("atlas"), body.get("dirs") or [])
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    hub.run_sync()
    return res


@app.get("/api/suite/health")
def health():
    return {"ok": True, "version": __version__, "modules": ["pdf", "expiry", "atlas"]}


@app.post("/api/suite/expiry/upload")
async def upload_expiry(file: UploadFile, request: Request):
    """Manual drop of a NEARLY_EXPIRED file (same validation as the network fetch)."""
    _require_local(request)
    suffix = Path(file.filename or "data.csv").suffix.lower()
    if suffix not in (".csv", ".txt", ".xlsx"):
        raise HTTPException(400, "รองรับเฉพาะ .csv .txt .xlsx")
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / f"upload{suffix}"
        with dst.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        res = expiry_data.install_file(dst, file.filename)
    if not res["ok"]:
        raise HTTPException(422, res["error"])
    hub.run_sync()
    return res


# ---------- expiry module ----------
@app.get("/m/expiry")
def expiry_redirect():
    return RedirectResponse("/m/expiry/")


@app.get("/m/expiry/")
def expiry_index(request: Request):
    return _page(request, "expiry", WEB_DIR / "modules" / "expiry" / "index.html")


@app.get("/m/expiry/{name}")
def expiry_file(name: str):
    if name in ("data.csv", "data.xlsx", "status.json", "app-config.json"):
        p = expiry_dir() / name
        if p.is_file():
            return FileResponse(p, headers={"Cache-Control": "no-store"})
        if name == "status.json" and expiry_data.data_file():  # data dropped in by hand, no fetch has run
            return JSONResponse({"success": True, "fileName": expiry_data.data_file().name, "rowCount": len(expiry_data.load_rows()), "errorMessage": ""})
        raise HTTPException(404)
    p = WEB_DIR / "modules" / "expiry" / name
    if p.is_file() and p.name != "index.html":
        return FileResponse(p)
    raise HTTPException(404)


app.mount("/m/expiry/assets", StaticFiles(directory=str(WEB_DIR / "modules" / "expiry" / "assets"), check_dir=False), name="expiry-assets")


# ---------- atlas module ----------
@app.get("/m/atlas")
def atlas_redirect():
    return RedirectResponse("/m/atlas/")


@app.get("/m/atlas/")
def atlas_index(request: Request):
    return _page(request, "atlas", WEB_DIR / "modules" / "atlas" / "index.html")


app.include_router(atlas_api.router, prefix="/m/atlas")


# ---------- pdf module (the original app, mounted whole) ----------


@app.get("/m/pdf/")
def pdf_index(request: Request):
    return _page(request, "pdf", pdf_module.FRONTEND_DIR / "index.html")


app.mount("/m/pdf", pdf_app, name="pdf")


# ---------- shell ----------
@app.get("/")
def shell():
    return FileResponse(WEB_DIR / "shell" / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/shell", StaticFiles(directory=str(WEB_DIR / "shell")), name="shell")
