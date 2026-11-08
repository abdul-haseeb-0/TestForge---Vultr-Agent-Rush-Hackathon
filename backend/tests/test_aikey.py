import json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import pytest
from fastapi.testclient import TestClient
from app.main import app, Base, engine
from app.config import settings
from app import aikey

client = TestClient(app)
SECRET = "sk-test-1234567890abcdef"

class Fake(BaseHTTPRequestHandler):
    seen = []
    reject_max_completion_tokens = False
    def log_message(self, *a): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append((self.headers.get("Authorization"), body))
        if Fake.reject_max_completion_tokens and "max_completion_tokens" in body:
            self.send_response(400); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "Unsupported parameter: max_completion_tokens", "type": "invalid_request_error"}}).encode()); return
        if self.headers.get("Authorization") != "Bearer " + SECRET:
            self.send_response(401); self.send_header("Content-Type", "application/json"); self.end_headers()
            self.wfile.write(json.dumps({"error": {"message": "bad key"}}).encode()); return
        out = {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
               "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "```json\n{\"summary\":\"ok\",\"findings\":[]}\n```" if body.get("response_format") else "ok"}}]}
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(json.dumps(out).encode())

@pytest.fixture(scope="module")
def fake():
    srv = HTTPServer(("127.0.0.1", 0), Fake); threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/v1"
    srv.shutdown()

@pytest.fixture(autouse=True)
def clean():
    Base.metadata.create_all(bind=engine)
    client.delete("/api/settings/ai"); Fake.seen.clear(); Fake.reject_max_completion_tokens = False
    settings().ai_allow_private_url = False
    yield
    settings().ai_allow_private_url = False

def test_starts_unconfigured():
    r = client.get("/api/settings/ai").json()
    assert r["configured"] is False and r["last4"] == ""
    assert client.get("/api/config").json()["ai_configured"] is False

def test_save_key_never_returned_and_encrypted_at_rest(fake):
    settings().ai_allow_private_url = True
    r = client.put("/api/settings/ai", json={"api_key": SECRET, "base_url": fake, "model": "m1"})
    assert r.status_code == 200
    assert SECRET not in r.text and r.json()["last4"] == SECRET[-4:] and r.json()["source"] == "ui"
    assert SECRET not in client.get("/api/settings/ai").text
    assert client.get("/api/config").json()["ai_configured"] is True
    from app.db import SessionLocal; from app.models import AppSetting
    with SessionLocal() as db: stored = db.get(AppSetting, "ai_api_key").value
    assert stored and SECRET not in stored

def test_blank_key_keeps_existing_and_updates_model(fake):
    settings().ai_allow_private_url = True
    client.put("/api/settings/ai", json={"api_key": SECRET, "base_url": fake, "model": "m1"})
    r = client.put("/api/settings/ai", json={"api_key": "", "base_url": fake, "model": "m2"}).json()
    assert r["configured"] and r["last4"] == SECRET[-4:] and r["model"] == "m2"

def test_delete_key(fake):
    settings().ai_allow_private_url = True
    client.put("/api/settings/ai", json={"api_key": SECRET, "base_url": fake, "model": "m1"})
    assert client.delete("/api/settings/ai").json()["configured"] is False

@pytest.mark.parametrize("bad", ["short", "has space in it 12345", "x" * 401])
def test_rejects_malformed_key(bad):
    assert client.put("/api/settings/ai", json={"api_key": bad}).status_code == 400

def test_ssrf_private_base_url_blocked():
    for u in ("http://127.0.0.1:9/v1", "http://localhost/v1", "http://169.254.169.254/latest", "ftp://example.com"):
        assert client.put("/api/settings/ai", json={"api_key": SECRET, "base_url": u}).status_code == 400

def test_connection_test_success_and_failure(fake):
    settings().ai_allow_private_url = True
    assert client.post("/api/settings/ai/test").status_code == 400  # no key yet
    client.put("/api/settings/ai", json={"api_key": "wrong-key-123456", "base_url": fake, "model": "m"})
    r = client.post("/api/settings/ai/test").json()
    assert r["ok"] is False and "wrong-key-123456" not in r["message"]
    client.put("/api/settings/ai", json={"api_key": SECRET, "base_url": fake, "model": "m"})
    r = client.post("/api/settings/ai/test").json()
    assert r["ok"] is True, r

def test_works_with_providers_that_reject_max_completion_tokens(fake):
    settings().ai_allow_private_url = True
    Fake.reject_max_completion_tokens = True
    client.put("/api/settings/ai", json={"api_key": SECRET, "base_url": fake, "model": "m"})
    assert client.post("/api/settings/ai/test").json()["ok"] is True
    assert any("max_tokens" in b for _, b in Fake.seen)

def test_diagnose_uses_ui_key_and_parses_fenced_json(fake):
    settings().ai_allow_private_url = True
    from app.ai import diagnose
    assert diagnose({}, {"findings": []}) is None
    client.put("/api/settings/ai", json={"api_key": SECRET, "base_url": fake, "model": "m"})
    assert diagnose({"console_errors": []}, {"findings": []}) == {"summary": "ok", "findings": []}
    assert Fake.seen[-1][0] == "Bearer " + SECRET

def test_admin_token_protects_settings():
    settings().settings_admin_token = "s3cret"
    try:
        assert client.get("/api/settings/ai").status_code == 401
        assert client.put("/api/settings/ai", json={"api_key": SECRET}).status_code == 401
        assert client.get("/api/settings/ai", headers={"X-Admin-Token": "s3cret"}).status_code == 200
    finally: settings().settings_admin_token = ""

