"""Serve the unchanged sibling pages from a sub-path of the suite.

Atlas and the expiry page call absolute URLs (`/api/...`, `/export/...`).
Mounted at /m/<name>/ those would hit the suite root, so each page gets a
tiny script injected as the first thing in <head> that:
  * prefixes such fetch() URLs with /m/<name>
  * points the expiry page's PDF-master auto-fetch at the in-suite PDF app
  * lets the shell hand a barcode to the page's own search box
"""
from __future__ import annotations

import re
from pathlib import Path

_SEARCH = {
    "expiry": {"input": "#searchBox"},
    "atlas": {"input": "#q", "tab": "[data-tab=map]"},
    "pdf": {"input": "#globalSearch"},
}

_SCRIPT = """<script>(function(){
var NAME=%(name)s,P="/m/"+NAME,S=%(search)s,F=window.fetch;
window.fetch=function(u,o){if(typeof u==="string"&&/^\\/(api|export)\\//.test(u))u=P+u;return F.call(this,u,o)};
if(NAME==="expiry"){try{var K="expiry-pdf-tool-base-url",c=localStorage.getItem(K);if(!c||/^http:\\/\\/localhost:8000/.test(c))localStorage.setItem(K,"/m/pdf")}catch(e){}}
window.addEventListener("message",function(e){
 if(e.origin!==location.origin)return;var d=e.data;if(!d||d.type!=="suite:search")return;
 try{if(S.tab){var t=document.querySelector(S.tab);if(t)t.click()}
 var i=document.querySelector(S.input);if(i){i.value=String(d.q||"");i.dispatchEvent(new Event("input",{bubbles:true}));i.focus()}}catch(x){}
});
try{parent!==window&&parent.postMessage({type:"suite:ready",module:NAME},location.origin)}catch(e){}
})();</script>"""

_cache: dict[tuple[str, float], str] = {}


def render(name: str, html_path: Path) -> str:
    import json

    key = (name, html_path.stat().st_mtime)
    if key not in _cache:
        _cache.clear()
        text = html_path.read_text(encoding="utf-8")
        script = _SCRIPT % {"name": json.dumps(name), "search": json.dumps(_SEARCH[name])}
        m = re.search(r"<head[^>]*>", text, re.I)
        _cache[key] = text[: m.end()] + script + text[m.end():] if m else script + text
    return _cache[key]
