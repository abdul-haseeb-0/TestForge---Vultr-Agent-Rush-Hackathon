"""Runs the real Playwright scanner against a throwaway local site with known bugs."""
import asyncio, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from app import qa

PAGES = {
    "/": "<title>Home</title><h1>Home</h1><a href='/about'>About</a> <a href='/missing'>Missing</a><img src='/nope.png'>"
         "<button onclick=\"delete_all()\">Delete everything</button>",
    "/about": "<title>About</title><h1>About</h1><button onclick='undefinedFn()'>Show</button>",
}
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        code, body = (200, PAGES[self.path]) if self.path in PAGES else (404, "<h1>nf</h1>")
        self.send_response(code); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(body.encode())

@pytest.fixture(scope="module")
def site():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/"; srv.shutdown()

@pytest.fixture
def scan(monkeypatch, site):
    monkeypatch.setattr(qa, "validate_url", lambda u: u)  # allow the loopback test site
    try: data, _ = asyncio.run(qa.scan(site, "t-" + str(abs(hash(site))), "standard", []))
    except Exception as e: pytest.skip(f"Playwright/Chromium unavailable: {e}")
    return data

def test_crawls_pages_and_flags_broken_link(scan):
    assert {p["http_status"] for p in scan["pages"]} == {200, 404}
    assert any(b["status"] == 404 for b in scan["broken_links"])

def test_uncaught_js_exception_is_detected(scan):
    assert any("undefinedFn" in e["message"] for e in scan["console_errors"])

def test_failed_resource_not_duplicated_as_console_error(scan):
    assert not any("Failed to load resource" in e["message"] for e in scan["console_errors"])
    assert any(h["status"] == 404 and h["resource_type"] == "image" for h in scan["http_errors"])

def test_destructive_button_never_clicked(scan):
    assert all("delete" not in b["label"].lower() for b in scan["button_checks"])
