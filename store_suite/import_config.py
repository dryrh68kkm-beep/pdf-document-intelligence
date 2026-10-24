"""Pull settings and data from the standalone programs, so nothing is typed twice.

Looks next to the Store Suite folder (e.g. C:\\LP-Tools\\ExpiryApp,
C:\\LP-Tools\\Ooslayout) for:

  expiry-dashboard   config.ps1 + fetch-data.ps1
                       -> expirySourceFolder / Basename / Extensions
                       -> its current data.csv (when Store Suite has none yet)
  Stock Atlas        server/StockAtlasServer.ps1 (+ server/config.json)
                       -> atlasSources (extra folders other programs drop files in)
                       -> saved layout / OOS / count / POG state (only keys
                          Store Suite has not saved yet - never overwritten)

`scan()` only reads; `apply()` copies, and never replaces something that
already exists in Store Suite.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from store_suite import atlas_api, expiry_data
from store_suite.config import load_config, save_config
from store_suite.paths import expiry_dir

APP_DIR = Path(__file__).resolve().parent.parent
_ASSIGN = re.compile(r"^\s*\$(\w+)\s*=\s*(.*?)\s*$")


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp874", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _strip_comment(value: str) -> str:
    out, quote = [], ""
    for ch in value:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            break
        out.append(ch)
    return "".join(out).strip()


def parse_config_ps1(text: str) -> dict:
    """The simple `$NAME = "value"` / `@('a','b')` / `$true` assignments config.ps1 uses."""
    values: dict = {}
    for line in text.splitlines():
        m = _ASSIGN.match(line)
        if not m:
            continue
        name, raw = m.group(1), _strip_comment(m.group(2))
        if raw.startswith("@("):
            values[name] = re.findall(r"[\"']([^\"']*)[\"']", raw)
        elif len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]:
            values[name] = raw[1:-1]
        elif raw.lower() in ("$true", "$false"):
            values[name] = raw.lower() == "$true"
        elif re.fullmatch(r"-?\d+", raw):
            values[name] = int(raw)
    return values


def _candidate_roots(extra: list[str] | None = None) -> list[Path]:
    roots = [APP_DIR.parent]
    roots += [Path(p) for p in (extra or []) if p]
    return roots


def scan(extra_dirs: list[str] | None = None) -> dict:
    found: dict = {"expiry": [], "atlas": []}
    seen: set[Path] = set()
    for root in _candidate_roots(extra_dirs):
        try:
            children = [root] + [c for c in root.iterdir() if c.is_dir()]
        except OSError:
            continue
        for d in children:
            try:
                d = d.resolve()
            except OSError:
                continue
            if d in seen or d == APP_DIR:
                continue
            seen.add(d)
            cfg_ps1 = d / "config.ps1"
            if cfg_ps1.is_file() and (d / "fetch-data.ps1").is_file():
                found["expiry"].append(_describe_expiry(d, cfg_ps1))
            if (d / "server" / "StockAtlasServer.ps1").is_file():
                found["atlas"].append(_describe_atlas(d))
    return found


def _describe_expiry(root: Path, cfg_ps1: Path) -> dict:
    v = parse_config_ps1(_read_text(cfg_ps1))
    folder = str(v.get("SOURCE_FOLDER") or "")
    if "REPLACE_ME" in folder:
        folder = ""
    www = Path(v["LOCAL_DATA_PATH"]) if v.get("LOCAL_DATA_PATH") else root / "www"
    data = next((p for p in (www / "data.csv", www / "data.xlsx") if p.is_file()), None)
    return {
        "path": str(root),
        "expirySourceFolder": folder,
        "expirySourceBasename": v.get("SOURCE_FILE_BASENAME") or "",
        "expirySourceExtensions": v.get("SOURCE_FILE_EXTENSIONS") or [],
        "dataFile": str(data) if data else "",
        "storeCodes": v.get("STORE_CODES") or [],
    }


def _describe_atlas(root: Path) -> dict:
    cfg: dict = {}
    for name in ("config.json", "config.example.json"):
        p = root / "server" / name
        if p.is_file():
            try:
                cfg = json.loads(_read_text(p))
            except ValueError:
                cfg = {}
            break
    data_dir = root / str(cfg.get("dataDir") or "data")
    sources = [
        {"name": str(s.get("name") or s["path"]), "path": str(s["path"])}
        for s in cfg.get("sources") or []
        if isinstance(s, dict) and s.get("path") and not re.fullmatch(r"data[\\/]+inbox", str(s["path"]).strip(), re.I)
    ]
    state_dir = data_dir / "state"
    states = [k for k in atlas_api.STATE_KEYS if (state_dir / f"{k}.json").is_file()]
    return {
        "path": str(root),
        "atlasSources": sources,
        "stateDir": str(state_dir),
        "states": states,
        "pogFolders": [str(p.get("path")) for p in cfg.get("pog") or [] if isinstance(p, dict) and p.get("path")],
    }


def apply(expiry_path: str | None, atlas_path: str | None, extra_dirs: list[str] | None = None) -> dict:
    """Import from the chosen installs (paths must be ones scan() found)."""
    found = scan(extra_dirs)
    report: dict = {"settings": {}, "copied": [], "skipped": []}
    cfg = load_config()
    patch: dict = {}

    if expiry_path:
        e = next((x for x in found["expiry"] if x["path"] == str(Path(expiry_path).resolve())), None)
        if e is None:
            raise ValueError("ไม่พบ expiry-dashboard ที่เลือก")
        if e["expirySourceFolder"] and not cfg.get("expirySourceFolder"):
            patch["expirySourceFolder"] = e["expirySourceFolder"]
        if e["expirySourceBasename"] and cfg.get("expirySourceBasename") == "NEARLY_EXPIRED_1003":
            patch["expirySourceBasename"] = e["expirySourceBasename"]
        if e["expirySourceExtensions"] and e["expirySourceExtensions"] != cfg.get("expirySourceExtensions"):
            patch["expirySourceExtensions"] = e["expirySourceExtensions"]
        if e["dataFile"] and not expiry_data.data_file():
            res = expiry_data.install_file(Path(e["dataFile"]))
            (report["copied"] if res.get("ok") else report["skipped"]).append({"item": "expiry data", **res})
        elif e["dataFile"]:
            report["skipped"].append({"item": "expiry data", "reason": "Store Suite มีไฟล์อยู่แล้ว ไม่ทับ"})
        if e["storeCodes"]:
            report["skipped"].append({"item": "หลายร้าน (STORE_CODES)", "reason": "Store Suite ยังรองรับไฟล์เดียว"})

    if atlas_path:
        a = next((x for x in found["atlas"] if x["path"] == str(Path(atlas_path).resolve())), None)
        if a is None:
            raise ValueError("ไม่พบ Stock Atlas ที่เลือก")
        have = {s["path"] for s in cfg.get("atlasSources") or [] if isinstance(s, dict)}
        merged = list(cfg.get("atlasSources") or []) + [s for s in a["atlasSources"] if s["path"] not in have]
        if len(merged) != len(cfg.get("atlasSources") or []):
            patch["atlasSources"] = merged
        for key in a["states"]:
            dst = atlas_api.state_file(key)
            if dst.is_file():
                report["skipped"].append({"item": f"atlas {key}", "reason": "Store Suite มีอยู่แล้ว ไม่ทับ"})
                continue
            src = Path(a["stateDir"]) / f"{key}.json"
            if atlas_api._validate_state(key, src.read_bytes()):  # same checks as a normal save
                report["skipped"].append({"item": f"atlas {key}", "reason": "ไฟล์ไม่ถูกรูปแบบ"})
                continue
            shutil.copyfile(src, dst)
            report["copied"].append({"item": f"atlas {key}"})
        if a["pogFolders"]:
            report["skipped"].append({"item": "โฟลเดอร์ POG", "reason": "Store Suite ยังไม่สแกนโฟลเดอร์ POG อัตโนมัติ"})

    if patch:
        save_config(patch)
    report["settings"] = patch
    return report
