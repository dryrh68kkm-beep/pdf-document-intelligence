"""The sync hub: one barcode-keyed view over all three programs.

  expiry-dashboard -> data.csv rows (stock qty, days left, dept)
  Stock Atlas      -> stock-count fixtures (which home a barcode sits in)
                      + OOS / Pick Check items
  PDF Intelligence -> delivery-document product rows (verified name, dept)

Nothing is copied into a second database: every lookup reads the owning
program's own store (cached by file mtime / short TTL), so a change in one
program is visible to the others on the next request. `run_sync()` pulls
fresh expiry data, then writes cross-program CSVs where each program
already looks for outside data (Atlas export folder).
"""
from __future__ import annotations

import csv
import io
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from store_suite import atlas_api, expiry_data
from store_suite.config import load_config
from store_suite.paths import WEB_DIR, atlas_export_dir, get_data_dir

_BUNDLED_COUNT = WEB_DIR / "modules" / "atlas" / "count-data.json"
_PDF_TTL = 15.0


def _num(v, default=None):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def _bc(v) -> str:
    s = str(v if v is not None else "").strip()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]  # Excel turned the barcode into a float
    return s


class Hub:
    def __init__(self, pdf_products: Callable[[], list[dict]] | None = None) -> None:
        self._pdf_products = pdf_products
        self._lock = threading.Lock()
        self._count_cache: tuple | None = None
        self._count_idx: dict[str, dict] = {}
        self._pdf_cache: tuple[float, dict[str, dict]] = (0.0, {})
        self.last_sync: dict = self._load_sync_state()

    # ---------- expiry ----------
    def expiry_index(self) -> dict[str, list[dict]]:
        idx: dict[str, list[dict]] = {}
        for r in expiry_data.load_rows():
            b = _bc(r.get("BAR_CODE"))
            if b:
                idx.setdefault(b, []).append(r)
        return idx

    # ---------- atlas ----------
    def count_index(self) -> dict[str, dict]:
        """barcode -> {name, article, homes: {fixture: qty}} from the shared
        count state, falling back to the count database bundled with Atlas."""
        f = atlas_api.state_file("count")
        src = f if f.is_file() else _BUNDLED_COUNT
        try:
            st = src.stat()
        except OSError:
            return {}
        key = (str(src), st.st_mtime_ns)
        if self._count_cache == key:
            return self._count_idx
        try:
            data = json.loads(src.read_text(encoding="utf-8-sig"))
            products = data.get("products") or []
            idx: dict[str, dict] = {}
            for fi, fixture, pi, qty in data.get("rows") or []:
                if not (0 <= pi < len(products)):
                    continue
                barcode, article, name = (products[pi] + ["", "", ""])[:3]
                e = idx.setdefault(_bc(barcode), {"name": name, "article": article, "homes": {}})
                e["homes"][str(fixture)] = e["homes"].get(str(fixture), 0) + (qty or 0)
        except (OSError, ValueError, TypeError):
            return {}
        self._count_cache, self._count_idx = key, idx
        return idx

    def oos_index(self) -> dict[str, dict]:
        data = atlas_api.read_state("oos") or {}
        out: dict[str, dict] = {}
        for it in data.get("items") or []:
            if isinstance(it, dict) and it.get("barcode"):
                out[_bc(it["barcode"])] = it
        return out

    # ---------- pdf ----------
    def pdf_index(self) -> dict[str, dict]:
        now = time.monotonic()
        if now - self._pdf_cache[0] < _PDF_TTL or self._pdf_products is None:
            return self._pdf_cache[1]
        idx: dict[str, dict] = {}
        try:
            for p in self._pdf_products():
                fields = p.get("fields") or {}
                barcode = _bc((fields.get("barcode") or {}).get("value"))
                if not barcode or p.get("deletedAt"):
                    continue
                e = idx.setdefault(barcode, {"name": "", "department": "", "documents": [], "reviewRequired": False})
                e["name"] = (fields.get("name") or {}).get("value") or e["name"]
                e["department"] = p.get("department") or e["department"]
                e["reviewRequired"] = e["reviewRequired"] or bool(p.get("reviewRequired"))
                if p.get("docFilename") and p["docFilename"] not in e["documents"]:
                    e["documents"].append(p["docFilename"])
        except Exception:  # noqa: BLE001 - PDF side being down must not break the other modules
            return self._pdf_cache[1]
        self._pdf_cache = (now, idx)
        return idx

    # ---------- joined views ----------
    def product(self, barcode: str) -> dict:
        barcode = _bc(barcode)
        ex = self.expiry_index().get(barcode, [])
        cnt = self.count_index().get(barcode)
        oos = self.oos_index().get(barcode)
        pdf = self.pdf_index().get(barcode)
        name = (ex[0].get("DESCRIPTION") if ex else "") or (pdf or {}).get("name") or (cnt or {}).get("name") or (oos or {}).get("name") or ""
        return {
            "barcode": barcode,
            "name": str(name).strip(),
            "found": bool(ex or cnt or oos or pdf),
            "expiry": [
                {"qty": _num(r.get("STOCK_QTY")), "daysLeft": _num(r.get("DAY_LEFT")), "subDept": r.get("SUB_DEPT_NAME"), "div": r.get("DIV"), "dept": r.get("DEPT")}
                for r in ex
            ],
            "homes": [{"home": h, "qty": q} for h, q in sorted((cnt or {}).get("homes", {}).items())],
            "oos": None if not oos else {"soh": oos.get("soh"), "checked": bool(oos.get("result")), "result": oos.get("result")},
            "pdf": pdf,
        }

    def search(self, q: str, limit: int = 20) -> list[dict]:
        q = q.strip()
        if not q:
            return []
        ql = q.lower()
        seen: dict[str, str] = {}
        for r in expiry_data.load_rows():
            b = _bc(r.get("BAR_CODE"))
            if b and (ql in b.lower() or ql in str(r.get("DESCRIPTION", "")).lower()):
                seen.setdefault(b, str(r.get("DESCRIPTION", "")))
        for b, e in self.count_index().items():
            if len(seen) >= limit * 3:
                break
            if ql in b.lower() or ql in str(e["name"]).lower():
                seen.setdefault(b, e["name"])
        for b, e in self.pdf_index().items():
            if ql in b.lower() or ql in str(e["name"]).lower():
                seen.setdefault(b, e["name"])
        return [self.product(b) for b in list(seen)[:limit]]

    def expiry_locations(self, max_days: float | None = 30) -> list[dict]:
        """Expiring items with the homes they were counted in and OOS state."""
        cnt, oos, pdf = self.count_index(), self.oos_index(), self.pdf_index()
        out = []
        for r in expiry_data.load_rows():
            b = _bc(r.get("BAR_CODE"))
            days = _num(r.get("DAY_LEFT"))
            if not b or (max_days is not None and (days is None or days > max_days)):
                continue
            homes = sorted((cnt.get(b) or {}).get("homes", {}))
            o = oos.get(b)
            out.append({
                "barcode": b,
                "name": str(r.get("DESCRIPTION") or (pdf.get(b) or {}).get("name") or "").strip(),
                "subDept": r.get("SUB_DEPT_NAME") or "",
                "qty": _num(r.get("STOCK_QTY")),
                "daysLeft": days,
                "homes": homes,
                "oos": bool(o and not o.get("result")),
                "inPdf": b in pdf,
            })
        out.sort(key=lambda x: (x["daysLeft"] if x["daysLeft"] is not None else 1e9, x["barcode"]))
        return out

    def overview(self) -> dict:
        ex_rows = expiry_data.load_rows()
        loc = self.expiry_locations(max_days=None)
        status = expiry_data.read_status()
        oos = atlas_api.read_state("oos") or {}
        oos_items = [i for i in oos.get("items") or [] if isinstance(i, dict)]
        layout = atlas_api.read_state("layout") or {}
        pdf = self.pdf_index()
        return {
            "expiry": {
                "rows": len(ex_rows),
                "expired": sum(1 for x in loc if x["daysLeft"] is not None and x["daysLeft"] < 0),
                "within7": sum(1 for x in loc if x["daysLeft"] is not None and 0 <= x["daysLeft"] <= 7),
                "within30": sum(1 for x in loc if x["daysLeft"] is not None and 0 <= x["daysLeft"] <= 30),
                "located": sum(1 for x in loc if x["homes"]),
                "lastFetch": status.get("lastAttempt"),
                "lastFetchOk": status.get("success"),
                "error": status.get("errorMessage") or "",
            },
            "atlas": {
                "maps": len(layout.get("maps") or []),
                "oosOpen": sum(1 for i in oos_items if not i.get("result")),
                "oosTotal": len(oos_items),
                "countedProducts": len(self.count_index()),
                "sharedLayout": atlas_api.state_file("layout").is_file(),
            },
            "pdf": {"barcodes": len(pdf), "needReview": sum(1 for e in pdf.values() if e["reviewRequired"])},
            "links": {
                "expiryAndCounted": sum(1 for x in loc if x["homes"]),
                "expiryAndOos": sum(1 for x in loc if x["oos"]),
                "expiryAndPdf": sum(1 for x in loc if x["inPdf"]),
            },
            "lastSync": self.last_sync,
        }

    # ---------- sync ----------
    def _sync_state_path(self) -> Path:
        return get_data_dir() / "sync-state.json"

    def _load_sync_state(self) -> dict:
        try:
            return json.loads(self._sync_state_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def run_sync(self) -> dict:
        """1) fetch fresh expiry file  2) refresh PDF/Atlas indexes
        3) write cross-program CSVs into Atlas' export folder (the place its
        'results for other programs' contract already points to)."""
        with self._lock:
            report: dict = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), "steps": []}

            def step(name: str, fn: Callable[[], dict]) -> None:
                try:
                    res = fn()
                except Exception as exc:  # noqa: BLE001 - one failed step must not block the rest
                    res = {"ok": False, "error": str(exc)}
                report["steps"].append({"step": name, **res})

            step("expiry-fetch", lambda: expiry_data.fetch_from_source(load_config()))
            self._pdf_cache = (0.0, self._pdf_cache[1])
            step("pdf-index", lambda: {"ok": True, "barcodes": len(self.pdf_index())})
            step("atlas-index", lambda: {"ok": True, "countedProducts": len(self.count_index()), "oosItems": len(self.oos_index())})
            step("export-expiry-locations", self._export_expiry_locations)
            report["ok"] = all(s.get("ok", True) for s in report["steps"])
            self.last_sync = report
            try:
                self._sync_state_path().write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return report

    def _export_expiry_locations(self) -> dict:
        rows = self.expiry_locations(max_days=None)
        buf = io.StringIO(newline="")
        w = csv.writer(buf)
        w.writerow(["BAR_CODE", "DESCRIPTION", "SUB_DEPT_NAME", "STOCK_QTY", "DAY_LEFT", "HOMES", "OOS_OPEN", "IN_PDF_MASTER"])
        for r in rows:
            vals = [r["barcode"], r["name"], r["subDept"], r["qty"] if r["qty"] is not None else "", r["daysLeft"] if r["daysLeft"] is not None else "", " ".join(r["homes"]), int(r["oos"]), int(r["inPdf"])]
            w.writerow([("'" + v) if isinstance(v, str) and v[:1] in "=+-@" else v for v in vals])
        f = atlas_export_dir() / "expiry-locations.csv"
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_bytes(buf.getvalue().encode("utf-8-sig"))
        tmp.replace(f)
        return {"ok": True, "rows": len(rows), "file": f.name}
