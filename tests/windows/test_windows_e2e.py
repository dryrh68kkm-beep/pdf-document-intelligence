"""Real-process smoke/E2E test for the Windows CI job.

Unlike every other integration test in this repo (which drives the FastAPI
app in-process via TestClient), this spins up the *actual* server as a
subprocess - the same `uvicorn pdf_document_intelligence.api.app:app`
entrypoint run.bat/run.sh use - and talks to it over a real HTTP socket.
That is deliberate: the point of the Windows CI job (see the spec this
implements) is to catch Windows-specific breakage that an in-process test
can mask - path separators, file locking semantics, LOCALAPPDATA
resolution, a server that fails to bind or serve static files at all on
that OS.

Written to also pass on Linux/macOS (nothing here is Windows-only syntax)
so it can be sanity-checked locally in this sandbox even though the CI job
that *requires* it only runs on windows-latest.

Uses only synthetic, runtime-generated data (PDF via tests/synthetic_documents.py,
CSV built in this file) - no real company data or master file anywhere.
"""
from __future__ import annotations

import csv
import io
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.synthetic_documents import make_bigc_pdf

REPO_ROOT = Path(__file__).resolve().parents[2]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _LiveServer:
    def __init__(self, base_url: str, data_dir: Path, proc: subprocess.Popen):
        self.base_url = base_url
        self.data_dir = data_dir
        self.proc = proc

    def get(self, path: str, timeout: float = 30) -> tuple[int, bytes]:
        req = urllib.request.Request(self.base_url + path)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def post_file(self, path: str, field: str, filename: str, data: bytes, content_type: str) -> tuple[int, bytes]:
        boundary = "----pdiwintestboundary"
        body = io.BytesIO()
        body.write(f"--{boundary}\r\n".encode())
        body.write(
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'.encode()
        )
        body.write(f"Content-Type: {content_type}\r\n\r\n".encode())
        body.write(data)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        payload = body.getvalue()
        req = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


@pytest.fixture()
def live_server(tmp_path):
    """Boots the real app as a child process, bound to 127.0.0.1 on a free
    port (not the app's own 0.0.0.0 LAN-binding default from run.sh/run.bat,
    which this test does not touch) with an isolated, throwaway data
    directory - never the developer/CI machine's real app data."""
    data_dir = tmp_path / "app-data"
    port = _free_port()
    env = dict(os.environ)
    env["PDF_INTELLIGENCE_DATA_DIR"] = str(data_dir)
    env.pop("PDF_INTELLIGENCE_MASTER_CATALOG", None)

    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn",
            "pdf_document_intelligence.api.app:app",
            "--host", "127.0.0.1", "--port", str(port),
        ],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base_url = f"http://127.0.0.1:{port}"
    server = _LiveServer(base_url, data_dir, proc)
    try:
        deadline = time.time() + 45
        last_err = None
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
                raise RuntimeError(f"server process exited early (code {proc.returncode}):\n{out}")
            try:
                status, _ = server.get("/api/health", timeout=2)
                if status == 200:
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError) as exc:
                last_err = exc
            time.sleep(0.5)
        else:
            raise TimeoutError(f"server did not become healthy in time: {last_err}")
        yield server
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)


def test_health_endpoint_reachable(live_server):
    status, body = live_server.get("/api/health")
    assert status == 200
    assert b'"status"' in body


def test_root_and_static_frontend_served(live_server):
    status, body = live_server.get("/")
    assert status == 200
    assert len(body) > 0


def test_app_data_temp_and_snapshot_directories_are_created_and_writable(live_server):
    """The server process itself (not the test) creates these on a real
    Windows filesystem the first time it runs - covers LOCALAPPDATA-style
    resolution end-to-end, not just the path-join logic in isolation."""
    data_dir = live_server.data_dir
    assert data_dir.is_dir()
    assert (data_dir / "pdfs").is_dir()
    assert (data_dir / "backups").is_dir()

    probe = data_dir / "_windows_e2e_write_probe.txt"
    probe.write_text("ok", encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == "ok"
    probe.unlink()

    temp_probe = Path(tempfile.gettempdir()) / "pdi_windows_e2e_temp_probe.txt"
    temp_probe.write_text("ok", encoding="utf-8")
    assert temp_probe.read_text(encoding="utf-8") == "ok"
    temp_probe.unlink()


def test_synthetic_pdf_upload_and_persistence_flow(live_server, tmp_path):
    """Upload -> process -> list -> detail, driven over real HTTP against
    the live process, using only a runtime-generated synthetic PDF."""
    sample = make_bigc_pdf(tmp_path / "windows-e2e-synthetic.pdf")
    status, body = live_server.post_file(
        "/api/documents", "file", "synthetic.pdf", sample.read_bytes(), "application/pdf"
    )
    assert status == 200, body
    import json

    doc = json.loads(body)
    doc_id = doc["id"]

    deadline = time.time() + 120
    final = None
    while time.time() < deadline:
        s, b = live_server.get(f"/api/documents/{doc_id}")
        assert s == 200
        d = json.loads(b)
        if d["status"] in ("complete", "error"):
            final = d
            break
        time.sleep(1)
    assert final is not None, "document did not finish processing in time"
    assert final["status"] == "complete", final

    s, b = live_server.get("/api/products")
    assert s == 200
    products = json.loads(b)
    assert len(products) > 0

    s, b = live_server.get("/api/state")
    assert s == 200
    state = json.loads(b)
    assert state["documentCount"] == 1


def test_synthetic_master_csv_import(live_server):
    """CSV/Master import against a synthetic fixture, never real Master
    data - mirrors tests/integration/test_master_import_validation.py's own
    good-CSV shape."""
    header = "BARCODE,ART_SV_NAME,SUBCLASS_NAME,ART_NO,DEPARTMENT_NAME,DIVISION_NAME,CURRENT_COST"
    rows = [
        f"9900000000{i:02d},Synthetic Product {i},SUB,ART{i},BAKERY,04 DRY FOOD,{10 + i}.50"
        for i in range(5)
    ]
    csv_bytes = (header + "\n" + "\n".join(rows) + "\n").encode("utf-8")
    status, body = live_server.post_file(
        "/api/master/import", "file", "synthetic-master.csv", csv_bytes, "text/csv"
    )
    assert status == 200, body


def test_export_xlsx_after_processing_opens_with_openpyxl(live_server, tmp_path):
    """Depends on test_synthetic_pdf_upload_and_persistence_flow having run
    a document to completion first is *not* assumed - this test uploads its
    own synthetic document so it is independently runnable."""
    sample = make_bigc_pdf(tmp_path / "windows-e2e-export.pdf")
    status, body = live_server.post_file(
        "/api/documents", "file", "export-synthetic.pdf", sample.read_bytes(), "application/pdf"
    )
    assert status == 200, body
    import json

    doc_id = json.loads(body)["id"]

    deadline = time.time() + 120
    while time.time() < deadline:
        s, b = live_server.get(f"/api/documents/{doc_id}")
        d = json.loads(b)
        if d["status"] in ("complete", "error"):
            break
        time.sleep(1)
    assert d["status"] == "complete", d

    status, body = live_server.get("/api/export.xlsx")
    assert status == 200

    out_path = tmp_path / "export.xlsx"
    out_path.write_bytes(body)

    import openpyxl

    wb = openpyxl.load_workbook(out_path)
    assert len(wb.sheetnames) > 0
    ws = wb[wb.sheetnames[0]]
    assert ws.max_row >= 1
