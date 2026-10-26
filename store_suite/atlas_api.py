"""Stock Atlas server API (port of Ooslayout/server/StockAtlasServer.ps1).

The Atlas page talks to /api/info, /api/state/<key>, /api/files, /api/file,
/api/inbox/<name> and /api/export/<name>; Store Suite serves the same
contract under /m/atlas so the unchanged page works inside the suite
(see shim.py for the URL prefixing) and shares its state across devices.
"""
from __future__ import annotations

import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from store_suite.config import load_config
from store_suite.paths import atlas_backup_dir, atlas_export_dir, atlas_inbox_dir, atlas_state_dir

router = APIRouter()

STATE_KEYS = ("layout", "oos", "count", "draw", "pog")
# What each shared state must contain; a broken upload must never replace a good file.
STATE_SCHEMA = {"layout": ("maps",), "oos": ("items",), "count": ("files", "rows"), "draw": ("boards",), "pog": ("list",)}
FILE_EXT = {".xls", ".xlsx", ".xlsb", ".xlsm", ".csv", ".txt", ".tsv", ".htm", ".html", ".xml", ".json"}
BACKUP_KEEP = 30
BACKUP_EVERY_MIN = {"layout": 0, "count": 0, "draw": 5, "oos": 10, "pog": 10}
MAX_BODY = 100 * 1024 * 1024
_lock = threading.Lock()


def _safe_name(name: str | None) -> str | None:
    if not name or len(name) > 200:
        return None
    if any(c in name for c in '\\/:*?"<>|') or name.startswith(".") or ".." in name:
        return None
    return name


def state_file(key: str) -> Path:
    return atlas_state_dir() / f"{key}.json"


def rev_of(path: Path) -> str:
    try:
        return str(path.stat().st_mtime_ns)
    except OSError:
        return ""


_state_cache: dict[str, tuple] = {}


def read_state(key: str):
    """Parsed shared state, or None when it has never been saved.

    Parsed once per change of the file (a saved OOS list or layout is several MB
    of JSON; every overview refresh used to re-parse it). Callers must treat the
    result as read-only."""
    f = state_file(key)
    try:
        st = f.stat()
    except OSError:
        _state_cache.pop(key, None)
        return None
    sig = (st.st_mtime_ns, st.st_size)
    hit = _state_cache.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        data = json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    _state_cache[key] = (sig, data)
    return data


def _validate_state(key: str, body: bytes) -> str:
    if len(body) < 2:
        return "invalid json"
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "invalid json"
    if not isinstance(obj, dict):
        return "invalid json"
    for k in STATE_SCHEMA[key]:
        if not isinstance(obj.get(k), list):
            return "invalid state data"
    if key == "layout":
        maps = obj["maps"]
        if not maps or any(not isinstance(m, dict) or not isinstance(m.get("objects"), list) for m in maps):
            return "invalid state data"
    if key == "draw" and not obj["boards"]:
        return "invalid state data"
    return ""


def _backup(key: str, f: Path, rev: str) -> None:
    if not f.is_file():
        return
    mins = BACKUP_EVERY_MIN[key]
    existing = sorted(atlas_backup_dir().glob(f"{key}-*.json"), reverse=True)
    if mins and existing and (time.time() - existing[0].stat().st_mtime) / 60 < mins:
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    dst = atlas_backup_dir() / f"{key}-{stamp}-r{rev}.json"
    dst.write_bytes(f.read_bytes())
    for old in sorted(atlas_backup_dir().glob(f"{key}-*.json"), reverse=True)[BACKUP_KEEP:]:
        old.unlink(missing_ok=True)


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def oos_folder() -> str:
    """Configured OOS report folder with {year} filled in ('' when not set)."""
    raw = str(load_config().get("oosSourceFolder") or "").strip()
    return raw.replace("{year}", str(datetime.now().year)).replace("{yyyy}", str(datetime.now().year))


def _sources() -> list[dict]:
    out = [{"name": "Inbox (data/inbox)", "path": str(atlas_inbox_dir())}]
    if oos_folder():
        out.append({"name": "รายงาน OOS (โฟลเดอร์เครือข่าย) - เฉพาะไฟล์ล่าสุด", "path": oos_folder(), "latestOnly": True})
    for s in load_config().get("atlasSources") or []:
        if isinstance(s, dict) and s.get("path"):
            out.append({"name": str(s.get("name") or s["path"]), "path": str(s["path"])})
    return out


_executor = ThreadPoolExecutor(max_workers=2)
_list_cache: dict[str, tuple[float, dict]] = {}
_list_pending: dict[str, object] = {}
_LIST_TTL = 20.0


def _is_unc(path: str) -> bool:
    return path.startswith("\\\\") or path.startswith("//")


def _list_source(i: int, src: dict) -> dict:
    """Local folders are listed directly. A network share can hang for half a minute when
    unreachable, so it is listed in the background: callers get the last result (or
    'scanning') instead of waiting."""
    path = src["path"]
    if not _is_unc(path):
        return {**_list_source_now(i, src)}
    now = time.monotonic()
    cached = _list_cache.get(path)
    fut = _list_pending.get(path)
    if fut is not None and fut.done():
        try:
            _list_cache[path] = (time.monotonic(), fut.result())
        except Exception as exc:  # noqa: BLE001
            _list_cache[path] = (time.monotonic(), {"ok": False, "error": str(exc), "files": []})
        _list_pending.pop(path, None)
        fut = None
        cached = _list_cache[path]
    if (cached is None or now - cached[0] > _LIST_TTL) and fut is None:
        _list_pending[path] = _executor.submit(_list_source_now, i, src)
        fut = _list_pending[path]
    if cached is None:
        try:
            res = fut.result(timeout=4)
            _list_cache[path] = (time.monotonic(), res)
            _list_pending.pop(path, None)
            return {**res, "id": i, "name": src["name"], "path": path}
        except Exception:  # noqa: BLE001 - still scanning / timed out
            return {"id": i, "name": src["name"], "path": path, "ok": True, "error": "", "files": [], "scanning": True}
    return {**cached[1], "id": i, "name": src["name"], "path": path, "scanning": fut is not None}


def _list_source_now(i: int, src: dict) -> dict:
    entry = {"id": i, "name": src["name"], "path": src["path"], "ok": True, "error": "", "files": []}
    try:
        folder = Path(src["path"])
        if not folder.is_dir():
            raise OSError("folder not found")
        # "~$x.xlsx" is the lock file Excel leaves while someone has the report open - never a report
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in FILE_EXT and not p.name.startswith(("~$", "."))]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        if src.get("latestOnly"):
            files = files[:1]  # this folder holds years of daily reports: only the newest one is wanted
        entry["files"] = [{"name": p.name, "size": p.stat().st_size, "mtime": int(p.stat().st_mtime * 1000)} for p in files[:200]]
    except OSError as exc:
        entry["ok"], entry["error"] = False, str(exc)
    return entry


def _json(body, status: int = 200, headers: dict | None = None) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store", **(headers or {})})


@router.get("/api/info")
def info():
    return _json({
        "server": "stock-atlas",
        "version": "suite-1",
        "host": socket.gethostname(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "sources": [s["name"] for s in _sources()],
        "pog": [],
        "exportDir": str(atlas_export_dir()),
    })


@router.api_route("/api/state/{key}", methods=["GET", "PUT"])
async def state(key: str, request: Request):
    if key not in STATE_KEYS:
        return _json({"error": "unknown state"}, 404)
    f = state_file(key)
    rev = rev_of(f)
    if request.method == "GET":
        if not rev:
            return Response(status_code=204, headers={"X-Rev": "0", "Cache-Control": "no-store"})
        if request.headers.get("x-if-rev") == rev:
            return Response(status_code=304, headers={"X-Rev": rev})
        return Response(f.read_bytes(), media_type="application/json; charset=utf-8", headers={"X-Rev": rev, "Cache-Control": "no-store"})
    body = await request.body()
    if len(body) > MAX_BODY:
        return _json({"error": "too large"}, 413)
    with _lock:
        rev = rev_of(f)
        want = request.headers.get("x-if-rev")
        cur = rev or "0"
        if want is not None and want != "*" and want != cur:
            return _json({"error": "conflict", "rev": rev}, 409, {"X-Rev": rev})
        why = _validate_state(key, body)
        if why:
            return _json({"error": why}, 400)
        _backup(key, f, rev)
        _atomic_write(f, body)
        new = rev_of(f)
    return _json({"rev": new}, 200, {"X-Rev": new})


@router.get("/api/pog/list")
def pog_list():
    return _json([])  # planogram PDF folders are a Windows-share feature of the standalone server


@router.get("/api/files")
def files():
    return _json([_list_source(i, s) for i, s in enumerate(_sources())])


@router.get("/api/file")
def get_file(src: int = -1, name: str = ""):
    srcs = _sources()
    safe = _safe_name(name)
    if src < 0 or src >= len(srcs) or not safe:
        return _json({"error": "bad file"}, 400)
    f = Path(srcs[src]["path"]) / safe
    if not f.is_file():
        return _json({"error": "not found"}, 404)
    return FileResponse(f, media_type="application/octet-stream")


@router.api_route("/api/inbox/{name}", methods=["PUT", "POST"])
async def inbox(name: str, request: Request):
    safe = _safe_name(name)
    if not safe or Path(safe).suffix.lower() not in FILE_EXT:
        return _json({"error": "bad name or file type"}, 400)
    body = await request.body()
    if len(body) > MAX_BODY:
        return _json({"error": "too large"}, 413)
    _atomic_write(atlas_inbox_dir() / safe, body)
    return _json({"ok": True, "name": safe})


@router.api_route("/api/export/{name}", methods=["GET", "PUT"])
@router.api_route("/export/{name}", methods=["GET", "PUT"])
async def export(name: str, request: Request):
    safe = _safe_name(name)
    if not safe or Path(safe).suffix.lower() not in (".csv", ".json"):
        return _json({"error": "bad name"}, 400)
    f = atlas_export_dir() / safe
    if request.method == "PUT":
        _atomic_write(f, await request.body())
        return _json({"ok": True})
    if not f.is_file():
        return _json({"error": "not found"}, 404)
    mt = "application/json; charset=utf-8" if safe.endswith(".json") else "text/csv; charset=utf-8"
    return FileResponse(f, media_type=mt, headers={"Cache-Control": "no-store"})
