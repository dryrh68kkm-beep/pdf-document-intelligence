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
    def __init__(self, pdf_products: Callable[[], list[dict]] | None = None, pdf_documents: Callable[[], list[dict]] | None = None) -> None:
        self._pdf_products = pdf_products
        self._pdf_documents = pdf_documents
        self._pdf_stats: dict = {"docs": 0, "completeDocs": 0, "errorDocs": 0, "rows": 0, "needReview": 0, "nonProduct": 0}
        self._lock = threading.Lock()
        self._count_cache: tuple | None = None
        self._count_idx: dict[str, dict] = {}
        self._pdf_cache: tuple[float, dict[str, dict]] = (0.0, {})
        self._pdf_stamp = 0
        self._pdf_refreshing = False
        self._memo: dict[str, tuple] = {}
        self.last_sync: dict = self._load_sync_state()

    # ---------- derived-data cache ----------
    def _sig(self) -> tuple:
        """Cheap fingerprint of every input: results derived from it are reused until one changes."""
        def fs(p):
            try:
                st = p.stat()
                return (st.st_mtime_ns, st.st_size)
            except OSError:
                return None

        df = expiry_data.data_file()
        return (fs(df) if df else None, fs(atlas_api.state_file("count")), fs(atlas_api.state_file("oos")), fs(atlas_api.state_file("layout")), self._pdf_stamp)

    def _memoized(self, name: str, build):
        sig = self._sig()
        hit = self._memo.get(name)
        if hit and hit[0] == sig:
            return hit[1]
        value = build()
        self._memo[name] = (sig, value)
        return value

    # ---------- expiry ----------
    def expiry_index(self) -> dict[str, list[dict]]:
        def build():
            idx: dict[str, list[dict]] = {}
            for r in expiry_data.load_rows():
                b = _bc(r.get("BAR_CODE"))
                if b:
                    idx.setdefault(b, []).append(r)
            return idx

        return self._memoized("expiry_index", build)

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
        def build():
            data = atlas_api.read_state("oos") or {}
            out: dict[str, dict] = {}
            for it in data.get("items") or []:
                if isinstance(it, dict) and it.get("barcode"):
                    out[_bc(it["barcode"])] = it
            return out

        return self._memoized("oos_index", build)

    # ---------- pdf ----------
    def pdf_index(self) -> dict[str, dict]:
        now = time.monotonic()
        if now - self._pdf_cache[0] < _PDF_TTL or self._pdf_products is None:
            return self._pdf_cache[1]
        if self._pdf_cache[0] > 0:  # have an older index: serve it, refresh in the background
            if not self._pdf_refreshing:
                self._pdf_refreshing = True

                def refresh():
                    try:
                        self._build_pdf_index(time.monotonic())
                    finally:
                        self._pdf_refreshing = False

                threading.Thread(target=refresh, daemon=True).start()
            return self._pdf_cache[1]
        return self._build_pdf_index(now)

    def _build_pdf_index(self, now: float) -> dict[str, dict]:
        idx: dict[str, dict] = {}
        stats = {"docs": 0, "completeDocs": 0, "errorDocs": 0, "rows": 0, "needReview": 0, "nonProduct": 0}
        try:
            for d in (self._pdf_documents() if self._pdf_documents else []):
                stats["docs"] += 1
                stats["completeDocs"] += d.get("status") == "complete"
                stats["errorDocs"] += d.get("status") == "error"
            for p in self._pdf_products():
                if not p.get("deletedAt"):
                    stats["rows"] += 1
                    stats["needReview"] += bool(p.get("reviewRequired"))
                    stats["nonProduct"] += bool(p.get("suspectedNonProduct"))
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
            self._pdf_cache = (now, self._pdf_cache[1])  # keep serving the last good index; retry after the TTL
            return self._pdf_cache[1]
        if self._pdf_cache[1].keys() != idx.keys() or self._pdf_stats != stats:
            self._pdf_stamp += 1
        self._pdf_cache = (now, idx)
        self._pdf_stats = stats
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

    def _search_corpus(self) -> list[tuple[str, str]]:
        def build():
            names: dict[str, str] = {}
            for r in expiry_data.load_rows():
                b = _bc(r.get("BAR_CODE"))
                if b:
                    names.setdefault(b, str(r.get("DESCRIPTION", "")))
            for source in (self.count_index(), self.pdf_index()):
                for b, e in source.items():
                    names.setdefault(b, str(e["name"]))
            return [(b, f"{b} {n}".lower()) for b, n in names.items()]

        return self._memoized("search_corpus", build)

    def search(self, q: str, limit: int = 20) -> list[dict]:
        q = q.strip().lower()
        if not q:
            return []
        self.pdf_index()
        hits = [b for b, text in self._search_corpus() if q in text][:limit]
        return [self.product(b) for b in hits]

    def expiry_locations(self, max_days: float | None = 30) -> list[dict]:
        """Expiring items with the homes they were counted in (sorted by days left)."""
        self.pdf_index()
        full = self._memoized("loc_all", self._build_locations)
        if max_days is None:
            return full
        return [x for x in full if x["daysLeft"] is not None and x["daysLeft"] <= max_days]

    def _build_locations(self) -> list[dict]:
        cnt, pdf = self.count_index(), self.pdf_index()
        out = []
        for r in expiry_data.load_rows():
            b = _bc(r.get("BAR_CODE"))
            days = _num(r.get("DAY_LEFT"))
            if not b:
                continue
            homes = sorted((cnt.get(b) or {}).get("homes", {}))
            out.append({
                "barcode": b,
                "name": str(r.get("DESCRIPTION") or (pdf.get(b) or {}).get("name") or "").strip(),
                "subDept": r.get("SUB_DEPT_NAME") or "",
                "qty": _num(r.get("STOCK_QTY")),
                "daysLeft": days,
                "homes": homes,
            })
        out.sort(key=lambda x: (x["daysLeft"] if x["daysLeft"] is not None else 1e9, x["barcode"]))
        return out

    def oos_items(self, pending_only: bool = True) -> list[dict]:
        """OOS / Pick Check items exactly as Atlas saved them - no expiry data mixed in."""
        full = self._memoized("oos_all", self._build_oos_items)
        return [x for x in full if not x["checked"]] if pending_only else full

    def _build_oos_items(self) -> list[dict]:
        out = []
        for it in (atlas_api.read_state("oos") or {}).get("items") or []:
            if not isinstance(it, dict):
                continue
            out.append({
                "barcode": _bc(it.get("barcode")),
                "name": str(it.get("name") or "").strip(),
                "soh": _num(it.get("soh")),
                "promo": bool(it.get("promo")),
                "checked": bool(it.get("result")),
                "result": it.get("result") or "",
            })
        out.sort(key=lambda x: (x["checked"], x["soh"] if x["soh"] is not None else 0, x["barcode"]))
        return out

    def overview(self) -> dict:
        core = self._memoized("overview", self._overview_core)
        status = expiry_data.read_status()  # small and changes without the data file changing
        return {
            **core,
            "expiry": {**core["expiry"], "lastFetch": status.get("lastAttempt"), "lastFetchOk": status.get("success"), "error": status.get("errorMessage") or ""},
            "atlas": {**core["atlas"], "oosFolder": self._oos_folder_info(core["atlas"].get("oosSource") or "")},
            "lastSync": self.last_sync,
        }

    def _oos_folder_info(self, imported_source: str) -> dict:
        """Newest report in the configured OOS folder, and whether it is the one that was imported."""
        folder = atlas_api.oos_folder()
        if not folder:
            return {"configured": False}
        srcs = atlas_api._sources()
        idx = next((i for i, s in enumerate(srcs) if s["path"] == folder), None)
        res = atlas_api._list_source(idx, srcs[idx]) if idx is not None else {"ok": False, "error": "", "files": []}
        files = res.get("files") or []
        newest = files[0] if files else None
        return {
            "configured": True, "path": folder, "ok": bool(res.get("ok")), "error": res.get("error") or "",
            "scanning": bool(res.get("scanning")), "fileCount": len(files),
            "newest": newest, "newestImported": bool(newest and imported_source and newest["name"] in imported_source),
        }

    def _overview_core(self) -> dict:
        ex_rows = expiry_data.load_rows()
        loc = self.expiry_locations(max_days=None)
        status = expiry_data.read_status()
        data_file = expiry_data.data_file()
        oos_state = atlas_api.read_state("oos") or {}
        oos_items = [i for i in oos_state.get("items") or [] if isinstance(i, dict)]
        layout = atlas_api.read_state("layout") or {}
        self.pdf_index()

        def days(x):
            return x["daysLeft"]

        buckets = {"expired": 0, "d0_7": 0, "d8_30": 0, "d31_90": 0, "over90": 0, "unknown": 0}
        by_dept: dict[str, dict] = {}
        total_qty = expired_qty = 0.0
        for x in loc:
            d, q = days(x), x["qty"] or 0
            k = ("unknown" if d is None else "expired" if d < 0 else "d0_7" if d <= 7 else "d8_30" if d <= 30 else "d31_90" if d <= 90 else "over90")
            buckets[k] += 1
            total_qty += q
            expired_qty += q if k == "expired" else 0
            e = by_dept.setdefault(x["subDept"] or "(ไม่ระบุ)", {"name": x["subDept"] or "(ไม่ระบุ)", "items": 0, "expired": 0, "within7": 0, "within30": 0, "qty": 0.0})
            e["items"] += 1
            e["qty"] += q
            e["expired"] += k == "expired"
            e["within7"] += k == "d0_7"
            e["within30"] += k in ("d0_7", "d8_30")
        depts = sorted(by_dept.values(), key=lambda e: (-e["expired"], -e["within7"], -e["items"]))[:15]

        soh = [_num(i.get("soh")) for i in oos_items]
        n_items = len(oos_items) or 1
        with_soh = sum(1 for v in soh if v is not None)
        with_status = sum(1 for i in oos_items if str(i.get("status") or "").strip())
        with_sales = sum(1 for i in oos_items if _num(i.get("sale7")) is not None or _num(i.get("avg")) is not None)
        # a real OOS report carries stock-on-hand, a status code and sales; a stock-count or product list does not
        looks_like_oos = (not oos_items) or (with_soh / n_items >= 0.2 or with_status / n_items >= 0.2 or with_sales / n_items >= 0.2)
        by_result: dict[str, int] = {}
        for i in oos_items:
            if i.get("result"):
                by_result[str(i["result"])] = by_result.get(str(i["result"]), 0) + 1
        src = oos_state.get("source")
        file_updated = None
        if data_file:
            try:
                file_updated = datetime.fromtimestamp(data_file.stat().st_mtime).astimezone().isoformat(timespec="seconds")
            except OSError:
                pass
        return {
            "expiry": {
                "rows": len(ex_rows),
                "expired": buckets["expired"],
                "within7": buckets["d0_7"],
                "within30": buckets["d0_7"] + buckets["d8_30"],
                "located": sum(1 for x in loc if x["homes"]),
                "buckets": buckets,
                "byDept": depts,
                "totalQty": total_qty,
                "expiredQty": expired_qty,
                "file": data_file.name if data_file else "",
                "fileUpdated": file_updated,
                "lastFetch": status.get("lastAttempt"),
                "lastFetchOk": status.get("success"),
                "error": status.get("errorMessage") or "",
            },
            "atlas": {
                "maps": len(layout.get("maps") or []),
                "oosOpen": sum(1 for i in oos_items if not i.get("result")),
                "oosTotal": len(oos_items),
                "oosNegative": sum(1 for v in soh if v is not None and v < 0),
                "oosZero": sum(1 for v in soh if v == 0),
                "oosPositive": sum(1 for v in soh if v is not None and v > 0),
                "oosPromo": sum(1 for i in oos_items if i.get("promo")),
                "oosByResult": by_result,
                "oosQuality": {"withSoh": with_soh, "withStatus": with_status, "withSales": with_sales, "looksLikeOos": looks_like_oos,
                               "sample": [{"barcode": str(i.get("barcode") or ""), "name": str(i.get("name") or "")} for i in oos_items[:3]]},
                "oosSource": src if isinstance(src, str) else (json.dumps(src, ensure_ascii=False) if src else ""),
                "oosImportedAt": oos_state.get("importedAt") or "",
                "countedProducts": len(self.count_index()),
                "sharedLayout": atlas_api.state_file("layout").is_file(),
            },
            "pdf": {**self._pdf_stats, "barcodes": len(self.pdf_index())},
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
        w.writerow(["BAR_CODE", "DESCRIPTION", "SUB_DEPT_NAME", "STOCK_QTY", "DAY_LEFT", "HOMES"])
        for r in rows:
            vals = [r["barcode"], r["name"], r["subDept"], r["qty"] if r["qty"] is not None else "", r["daysLeft"] if r["daysLeft"] is not None else "", " ".join(r["homes"])]
            w.writerow([("'" + v) if isinstance(v, str) and v[:1] in "=+-@" else v for v in vals])
        f = atlas_export_dir() / "expiry-locations.csv"
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_bytes(buf.getvalue().encode("utf-8-sig"))
        tmp.replace(f)
        return {"ok": True, "rows": len(rows), "file": f.name}
