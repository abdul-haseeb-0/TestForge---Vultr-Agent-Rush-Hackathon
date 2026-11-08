"""Full AI-repair loop against the DB-backed job store, with the AI call stubbed (no network/key needed)."""
import io, time, zipfile
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import repair as rp

client = TestClient(app)

def _zip():
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("proj/calc.py", "def add(a, b):\n    return a - b\n")
        f.writestr("proj/test_calc.py", "from calc import add\ndef test_add():\n    assert add(2, 3) == 5\n")
    return z.getvalue()

def _wait(jid, states, timeout=150):
    for _ in range(timeout):
        j = client.get(f"/api/repair/{jid}").json()
        if j["status"] in states and not j["busy"]: return j
        time.sleep(1)
    raise AssertionError(f"timed out in state {j['status']}: {j['message']}")

def _start(monkeypatch, patch):
    monkeypatch.setattr(rp, "ask_ai", lambda payload: patch)
    r = client.post("/api/repair", files=[("files", ("proj.zip", _zip(), "application/zip"))], data={"max_iterations": "3"})
    assert r.status_code == 202
    return r.json()["id"]

GOOD = {"diagnosis": "add subtracts", "patches": [{"path": "calc.py", "explanation": "use +", "edits": [{"search": "return a - b", "replace": "return a + b"}]}]}

def test_approve_apply_verifies_and_downloads(monkeypatch):
    jid = _start(monkeypatch, GOOD)
    j = _wait(jid, {"awaiting_approval", "needs_attention", "failed"})
    if j["status"] != "awaiting_approval": pytest.skip("pip/pytest could not be installed in this environment: " + j["message"])
    pid = j["iterations"][-1]["patches"][0]["id"]
    assert client.post(f"/api/repair/{jid}/patches/{pid}", json={"decision": "approve"}).status_code == 200
    assert client.post(f"/api/repair/{jid}/apply").status_code == 202
    j = _wait(jid, {"verified", "exhausted", "stalled", "failed", "needs_attention"})
    assert j["status"] == "verified"
    d = client.get(f"/api/repair/{jid}/download")
    assert d.status_code == 200
    names = zipfile.ZipFile(io.BytesIO(d.content)).namelist()
    assert "project/calc.py" in names and "report/REPORT.md" in names
    assert zipfile.ZipFile(io.BytesIO(d.content)).read("project/calc.py").decode().count("a + b") == 1

def test_rejecting_all_patches_stops_instead_of_looping(monkeypatch):
    jid = _start(monkeypatch, GOOD)
    j = _wait(jid, {"awaiting_approval", "needs_attention", "failed"})
    if j["status"] != "awaiting_approval": pytest.skip("pip/pytest could not be installed in this environment")
    pid = j["iterations"][-1]["patches"][0]["id"]
    client.post(f"/api/repair/{jid}/patches/{pid}", json={"decision": "reject"}); client.post(f"/api/repair/{jid}/apply")
    j = _wait(jid, {"needs_attention", "exhausted", "failed", "verified"})
    assert j["status"] == "needs_attention" and len(j["iterations"]) == 1

def test_job_survives_scratch_folder_loss(monkeypatch):
    """The DB is the source of truth: deleting the on-disk work dir must not lose the job."""
    import shutil
    jid = _start(monkeypatch, GOOD)
    j = _wait(jid, {"awaiting_approval", "needs_attention", "failed"})
    shutil.rmtree(rp.jd(jid), ignore_errors=True)
    assert client.get(f"/api/repair/{jid}").status_code == 200
