#!/usr/bin/env python3
"""Refresh the vendored copies of the sibling apps inside Store Suite.

Store Suite ships the expiry-dashboard page and the Stock Atlas single-file
app as static files under store_suite/web/modules/. Run this after those
repos change (pass the folder holding the sibling checkouts):

    python scripts/sync_modules.py [--siblings ..]
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ROOT / "store_suite" / "web" / "modules"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--siblings", default=str(ROOT.parent), help="folder containing expiry-dashboard/ and Ooslayout/")
    sib = Path(ap.parse_args().siblings)
    jobs = [
        (sib / "expiry-dashboard" / "www" / "index.html", MODULES / "expiry" / "index.html"),
        (sib / "expiry-dashboard" / "www" / "manifest.webmanifest", MODULES / "expiry" / "manifest.webmanifest"),
        (sib / "Ooslayout" / "Product_Home_Layout_Offline.html", MODULES / "atlas" / "index.html"),
        (sib / "Ooslayout" / "src" / "count-data.json", MODULES / "atlas" / "count-data.json"),
    ]
    for src, dst in jobs:
        if not src.is_file():
            print(f"missing {src}")
            return 1
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        print(f"{src} -> {dst.relative_to(ROOT)}")
    assets = sib / "expiry-dashboard" / "www" / "assets"
    if assets.is_dir():
        shutil.copytree(assets, MODULES / "expiry" / "assets", dirs_exist_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
