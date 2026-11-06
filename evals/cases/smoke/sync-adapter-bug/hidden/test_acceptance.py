import base64
import http.server
import json
import sqlite3
import threading
import urllib.parse

import pytest

COUNTS = {"contacts": 340, "companies": 120, "deals": 57}
ROW_KEY = {"contacts": "results", "companies": "results", "deals": "items"}
TOKEN = "real-token"


class Vendor(http.server.BaseHTTPRequestHandler):
    """The real protocol over a real socket, independent of the repo's sandbox module."""

    fail_on_page = {}  # entity -> behavior on its last-reached page (a later page where there is one)

    def log_message(self, *args):
        pass

    def _reply(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._reply(401, {"error": "unauthorized"})
        entity = parsed.path.rsplit("/", 1)[-1]
        if entity not in COUNTS:
            return self._reply(404, {"error": "unknown"})
        limit = min(int(query.get("limit", ["100"])[0]), 100)
        start = 0
        if "pageToken" in query:
            start = json.loads(base64.urlsafe_b64decode(query["pageToken"][0]))["o"]
        if start > 0 or COUNTS[entity] <= limit:
            behavior = self.server.fail_on_page.get(entity)
            if behavior == "malformed":
                return self._reply(200, {"unexpected": True})
            if behavior == "server_error":
                return self._reply(503, {"error": "unavailable"})
        rows = [{"id": f"{entity}-{n}"} for n in range(COUNTS[entity])][start:start + limit]
        page = {ROW_KEY[entity]: rows}
        if start + limit < COUNTS[entity]:
            page["nextPageToken"] = base64.urlsafe_b64encode(json.dumps({"o": start + limit}).encode()).decode()
        self._reply(200, page)


@pytest.fixture
def vendor():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Vendor)
    server.fail_on_page = {}
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def run_sync(py, tmp_path, server):
    path = tmp_path / "crm.db"
    done = py("-m", "crmsync", "--base-url", f"http://127.0.0.1:{server.server_port}",
              "--token", TOKEN, "--db", str(path), timeout=60)
    return done, path


def count(path, table):
    return sqlite3.connect(path).execute(f"SELECT COUNT(DISTINCT id) FROM {table}").fetchone()[0]


def test_contacts_and_companies_sync_fully(py, tmp_path, vendor):
    done, path = run_sync(py, tmp_path, vendor)
    assert done.returncode == 0, done.stderr
    assert count(path, "contacts") == 340
    assert count(path, "companies") == 120


def test_deals_sync_fully(py, tmp_path, vendor):
    done, path = run_sync(py, tmp_path, vendor)
    assert done.returncode == 0, done.stderr
    assert count(path, "deals") == 57


@pytest.mark.parametrize("entity", ["contacts", "deals"])
def test_malformed_page_fails_visibly(py, tmp_path, vendor, entity):
    vendor.fail_on_page = {entity: "malformed"}
    done, _ = run_sync(py, tmp_path, vendor)
    assert done.returncode != 0, "a page we can't use must not report success"
    assert "status=ok" not in done.stdout


def test_server_error_fails_visibly(py, tmp_path, vendor):
    vendor.fail_on_page = {"companies": "server_error"}
    done, _ = run_sync(py, tmp_path, vendor)
    assert done.returncode != 0
    assert "status=ok" not in done.stdout


def test_vendor_sandbox_module_not_modified(git):
    assert git("diff", "--name-only", "HEAD", "--", "crmsync/vendor_sandbox.py").strip() == ""
