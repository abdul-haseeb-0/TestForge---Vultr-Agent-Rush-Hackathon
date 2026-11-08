"""TestForge AI Repair & Verification.

Storage: PostgreSQL is the source of truth (job state, original upload, screenshots, logs).
The on-disk work folder is a disposable sandbox scratch dir, rebuilt from the database when missing.

Upload project -> sandboxed baseline checks -> AI diagnosis -> patch proposals ->
HUMAN approval -> apply -> re-run -> regression guard -> repeat (bounded) -> export.

Rules enforced in code, not in prompts:
  * uploaded code only runs inside Docker (no host execution unless explicitly opted in)
  * AI never writes files directly; only approved patches are applied
  * config/dependency/schema/test-file patches need an extra explicit confirmation
  * a patch round that breaks a previously passing check is rolled back automatically
  * "verified" only when every applicable check passes twice (verify run + final re-run)
"""
from __future__ import annotations
import difflib, io, json, os, re, shutil, signal, socket, subprocess, tempfile, threading, time, urllib.request, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from .config import settings
from .db import SessionLocal
from .models import RepairJob, RepairBlob
from . import aikey
from .security import validate_url

router = APIRouter(prefix="/api/repair", tags=["repair"])
SKIP = {"node_modules", ".git", "__pycache__", ".tf_deps", ".venv", "venv", "dist", ".pytest_cache", ".next"}
SENS_CFG = re.compile(r"(^|/)(package(-lock)?\.json|requirements[^/]*\.txt|pyproject\.toml|poetry\.lock|Dockerfile[^/]*|docker-compose[^/]*|\.env[^/]*|[^/]*\.sql|migrations?/|alembic/|schema[^/]*)", re.I)
SENS_TEST = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)(test_[^/]*|[^/]*_test\.py|[^/]*\.(test|spec)\.[jt]sx?)$", re.I)
TERMINAL = {"verified", "exhausted", "stalled", "needs_attention", "failed", "rolled_back"}
_lock = threading.RLock()
now = lambda: datetime.now(timezone.utc).isoformat()

# ---------- storage ----------
def base():
    p = settings().artifacts / "repair-scratch"; p.mkdir(parents=True, exist_ok=True); return p  # disposable; PostgreSQL holds the real data
def jd(i):
    if not re.fullmatch(r"[0-9a-f]{32}", i or ""): raise HTTPException(404, "Job not found")
    return base() / i
def load(i):
    jd(i)
    with SessionLocal() as db: r = db.get(RepairJob, i); data = json.loads(json.dumps(r.data)) if r else None
    if data is None: raise HTTPException(404, "Job not found")
    ensure_work(data); return data
def save(j):
    with _lock, SessionLocal() as db:
        r = db.get(RepairJob, j["id"])
        if not r: r = RepairJob(id=j["id"], created_at=datetime.now(timezone.utc)); db.add(r)
        r.name, r.status, r.updated_at, r.data = j["name"][:255], j["status"], datetime.now(timezone.utc), json.loads(json.dumps(j)); db.commit()
def put_blob(jid, kind, name, data: bytes):
    with SessionLocal() as db:
        db.execute(delete(RepairBlob).where(RepairBlob.job_id == jid, RepairBlob.kind == kind, RepairBlob.name == name))
        db.add(RepairBlob(job_id=jid, kind=kind, name=name, data=data)); db.commit()
def get_blob(jid, kind, name):
    with SessionLocal() as db: return db.scalar(select(RepairBlob.data).where(RepairBlob.job_id == jid, RepairBlob.kind == kind, RepairBlob.name == name))
def blobs(jid, kinds):
    with SessionLocal() as db: return [(r.kind, r.name, r.data) for r in db.execute(select(RepairBlob.kind, RepairBlob.name, RepairBlob.data).where(RepairBlob.job_id == jid, RepairBlob.kind.in_(kinds)))]
def drop_job(jid):
    shutil.rmtree(jd(jid), ignore_errors=True)
    with SessionLocal() as db:
        db.execute(delete(RepairBlob).where(RepairBlob.job_id == jid)); db.execute(delete(RepairJob).where(RepairJob.id == jid)); db.commit()
def ensure_work(j):
    """Rebuild the scratch folder from PostgreSQL: original upload + every patch still in 'applied' state, in order."""
    w = jd(j["id"]) / "work"
    if w.is_dir(): return
    data = get_blob(j["id"], "original", "project.zip")
    if data is None: return
    w.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z: z.extractall(w)  # archive was produced by ingest() from validated paths
    for it in sorted(j["iterations"], key=lambda x: x["n"]):
        for p in it["patches"]:
            if p["status"] == "applied": wr(safe(w, p["path"]), p["new_content"])
def recover():
    """Called at startup: a job left 'busy' by a crashed/restarted server is marked failed so it can be continued."""
    try:
        with SessionLocal() as db:
            for r in db.scalars(select(RepairJob)).all():
                if (r.data or {}).get("busy"):
                    d = json.loads(json.dumps(r.data)); d.update(busy=False, status="failed", message="Server restarted during a run. Use Continue to resume from the last safe state."); r.data, r.status = d, "failed"
            db.commit()
    except Exception: pass
def safe(root: Path, rel: str) -> Path:
    parts = [x for x in rel.replace("\\", "/").split("/") if x not in ("", ".")]
    if not parts or ".." in parts or any(":" in x for x in parts): raise HTTPException(400, f"Unsafe path: {rel}")
    p = root.joinpath(*parts).resolve()
    if root.resolve() not in p.parents: raise HTTPException(400, f"Unsafe path: {rel}")
    return p
def rd(f: Path) -> str:
    with open(f, encoding="utf-8", newline="") as h: return h.read()
def wr(f: Path, s: str):
    f.parent.mkdir(parents=True, exist_ok=True)
    with open(f, "w", encoding="utf-8", newline="") as h: h.write(s)
def walk(w: Path):
    for r, ds, fs in os.walk(w):
        ds[:] = [d for d in ds if d not in SKIP]
        for f in fs: yield Path(r) / f
def public(j, strip_content=False):
    o = json.loads(json.dumps(j))
    for it in o["iterations"]:
        it.pop("backup", None)
        if strip_content:
            for p in it["patches"]: p.pop("new_content", None)
    return o

# ---------- ingest ----------
def ingest(jid, uploads, git_url):
    w = jd(jid) / "work"; w.mkdir(parents=True)
    limit = settings().repair_max_upload_mb * 2**20; st = {"n": 0, "b": 0}
    def put(rel, data):
        if any(x in SKIP for x in rel.replace("\\", "/").split("/")): return
        st["n"] += 1; st["b"] += len(data)
        if st["n"] > 5000 or st["b"] > limit: raise HTTPException(413, "Project too large")
        wr_b = safe(w, rel); wr_b.parent.mkdir(parents=True, exist_ok=True); wr_b.write_bytes(data)
    if git_url:
        validate_url(git_url)
        r = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "clone", "--depth", "1", "--no-recurse-submodules", git_url, str(w)],
                           capture_output=True, timeout=120, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if r.returncode: raise HTTPException(400, "git clone failed: " + r.stderr.decode("utf-8", "replace")[-300:])
        shutil.rmtree(w / ".git", ignore_errors=True)
    for name, data in uploads:
        if name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    if sum(i.file_size for i in z.infolist()) > limit * 2: raise HTTPException(413, "Archive expands too large")
                    for i in z.infolist():
                        if i.is_dir() or ((i.external_attr >> 16) & 0o170000) == 0o120000: continue  # skip dirs/symlinks
                        put(i.filename, z.read(i))
            except zipfile.BadZipFile: raise HTTPException(400, "Invalid ZIP file")
        else: put(name, data)
    kids = list(w.iterdir())
    if len(kids) == 1 and kids[0].is_dir():  # strip single top-level folder
        tmp = w.parent / "_strip"; kids[0].rename(tmp)
        for k in tmp.iterdir(): shutil.move(str(k), str(w))
        tmp.rmdir()
    if not any(True for _ in walk(w)): raise HTTPException(400, "No project files received")
    buf = io.BytesIO()  # untouched original kept in PostgreSQL for rollback / rebuilding the scratch folder
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in walk(w): z.write(f, f.relative_to(w).as_posix())
    put_blob(jid, "original", "project.zip", buf.getvalue())

# ---------- planning (what to check) ----------
def make_plan(w: Path, s):
    files = list(walk(w)); names = {f.name for f in files}; plan = []; stack = []
    scripts, deps = {}, {}
    if "package.json" in names and (w / "package.json").is_file():
        try:
            d = json.loads(rd(w / "package.json")); scripts = d.get("scripts", {}); deps = {**d.get("dependencies", {}), **d.get("devDependencies", {})}
        except Exception: pass
        stack += ["Node.js"] + [n for k, n in (("react", "React"), ("vue", "Vue"), ("vite", "Vite"), ("next", "Next.js"), ("express", "Express")) if k in deps]
        N = "node:20-slim"
        plan.append(dict(id="T-install", name="Install dependencies (scripts disabled)", cmd="npm install --no-audit --no-fund --ignore-scripts", image=N, net=True, timeout=300))
        if "build" in scripts: plan.append(dict(id="T-build", name="Build", cmd="npm run build", image=N, net=False, timeout=300, needs="T-install"))
        elif "react" not in deps and "vue" not in deps:
            plan.append(dict(id="T-syntax", name="JavaScript syntax check", cmd="find . -name node_modules -prune -o -name '*.js' -print | xargs -r -n1 node --check", image=N, net=False, timeout=120))
        if scripts.get("test") and "no test specified" not in scripts["test"]:
            plan.append(dict(id="T-test", name="Unit tests", cmd="npm test --silent", image=N, net=False, timeout=300, needs="T-install"))
        start = s.get("start") or ("npm start" if "start" in scripts else "npm run dev -- --host 0.0.0.0" if "dev" in scripts else "")
        if start: plan.append(dict(id="T-smoke", name="Run app + browser smoke test", cmd=start, image=N, kind="smoke", timeout=120, needs="T-install", port=s.get("port") or (5173 if "vite" in deps else 3000)))
    pyf = [f for f in files if f.suffix == ".py"]
    if pyf:
        stack.append("Python"); P = "python:3.12-slim"
        tests = any(re.fullmatch(r"test_.*\.py|.*_test\.py", f.name) for f in pyf); req = (w / "requirements.txt").is_file()
        if tests or req: plan.append(dict(id="T-install", name="Install dependencies", cmd="pip install -q --no-cache-dir --target .tf_deps " + ("-r requirements.txt " if req else "") + ("pytest" if tests else ""), image=P, net=True, timeout=300))
        plan.append(dict(id="T-pysyntax", name="Python syntax/compile check", cmd="python -m compileall -q -x '(\\.tf_deps|node_modules|\\.venv)' .", image=P, net=False, timeout=120))
        if tests: plan.append(dict(id="T-pytest", name="Unit tests (pytest)", cmd="python -m pytest -x -q --tb=short -p no:cacheprovider", image=P, net=False, timeout=300, needs="T-install"))
        if s.get("start"): plan.append(dict(id="T-smoke", name="Run app + browser smoke test", cmd=s["start"], image=P, kind="smoke", timeout=120, needs="T-install" if (tests or req) else "", port=s.get("port") or 8000))
    if not plan and (w / "index.html").is_file():
        stack.append("Static HTML"); plan.append(dict(id="T-smoke", name="Serve + browser smoke test", cmd=s.get("start") or "python -m http.server 8000", image="python:3.12-slim", kind="smoke", timeout=60, port=s.get("port") or 8000))
    return stack, plan

# ---------- sandbox ----------
def tail(b, n=6000): return (b.decode("utf-8", "replace") if isinstance(b, bytes) else b)[-n:]
def _args(jid, cmd, image, net, extra=()):
    cfg = settings(); w = str(jd(jid) / "work"); name = "tf-" + uuid.uuid4().hex[:10]
    if cfg.repair_sandbox == "docker":
        if not shutil.which("docker"): return None, name, "Docker is not available. Install Docker (recommended) or set REPAIR_SANDBOX=process + REPAIR_ALLOW_UNSAFE_PROCESS=true (NOT isolated; development only)."
        a = ["docker", "run", "--name", name, "--memory", "1g", "--cpus", "1", "--pids-limit", "512", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
             "-v", f"{w}:/app", "-w", "/app", "-e", "HOME=/tmp", "-e", "CI=true", "-e", "PYTHONPATH=/app/.tf_deps", *extra]
        if hasattr(os, "getuid"): a += ["-u", f"{os.getuid()}:{os.getgid()}"]
        if not net and not extra: a += ["--network", "none"]
        return a + [image, "sh", "-c", cmd], name, ""
    if cfg.repair_sandbox == "process" and cfg.repair_allow_unsafe_process: return ["sh", "-c", cmd], name, ""
    return None, name, "Sandbox disabled. Set REPAIR_SANDBOX=docker."
def sh(jid, c):
    t0 = time.time(); a, name, err = _args(jid, c["cmd"], c["image"], c.get("net", False))
    if not a: return dict(code=-1, out=err, secs=0)
    docker = a[0] == "docker"
    if docker: a.insert(2, "--rm")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(jd(jid) / "work"), "CI": "true", "PYTHONPATH": str(jd(jid) / "work" / ".tf_deps")}
    try:
        r = subprocess.run(a, capture_output=True, timeout=c.get("timeout", 120), cwd=None if docker else str(jd(jid) / "work"), env=None if docker else env)
        return dict(code=r.returncode, out=tail(r.stdout + r.stderr), secs=round(time.time() - t0, 1))
    except subprocess.TimeoutExpired as e:
        if docker: subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        return dict(code=-1, out="TIMEOUT after %ss\n" % c.get("timeout") + tail((e.stdout or b"") + (e.stderr or b"")), secs=round(time.time() - t0, 1))
def smoke(jid, c, label):
    """Start the app in the sandbox, open it in a real browser, keep a screenshot as evidence."""
    port = int(c["port"]); s = socket.socket(); s.bind(("127.0.0.1", 0)); hp = s.getsockname()[1]; s.close()
    # NOTE: a published port needs a bridge network, so outbound traffic is NOT blocked during the smoke test (use a VM/worker for hostile code).
    a, name, err = _args(jid, c["cmd"], c["image"], True, extra=("-p", f"127.0.0.1:{hp}:{port}"))
    if not a: return dict(code=-1, out=err, secs=0, shot="")
    docker = a[0] == "docker"; t0 = time.time(); shot = ""; log = ""; ok = False
    if docker: a.insert(2, "-d")
    proc = None
    try:
        if docker: subprocess.run(a, capture_output=True, timeout=60)
        else: proc = subprocess.Popen(a, cwd=str(jd(jid) / "work"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True); hp = port
        url = f"http://127.0.0.1:{hp}/"; up = False
        for _ in range(60):
            try: urllib.request.urlopen(url, timeout=2); up = True; break
            except urllib.error.HTTPError: up = True; break
            except Exception: time.sleep(1)
        if not up: log = "App did not answer on port %s within 60s.\n" % port
        else:
            from playwright.sync_api import sync_playwright
            errs = []; fd, tmp = tempfile.mkstemp(suffix=".png"); os.close(fd)
            with sync_playwright() as pw:
                b = pw.chromium.launch(); pg = b.new_page(viewport={"width": 1280, "height": 800})
                pg.on("console", lambda m: errs.append("console.error: " + m.text) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errs.append("pageerror: " + str(e)))
                r = pg.goto(url, wait_until="load", timeout=20000); pg.wait_for_timeout(800)
                shot = f"{label}-{c['id']}.png"; pg.screenshot(path=tmp, full_page=True); b.close()
            put_blob(jid, "shots", shot, Path(tmp).read_bytes()); os.unlink(tmp)
            ok = (r.status if r else 0) < 400 and not errs
            log = f"HTTP {r.status if r else 'none'} at {url}\n" + "\n".join(errs[:20])
    except Exception as e: log += "Smoke test error: %s\n" % e
    finally:
        if docker:
            lg = subprocess.run(["docker", "logs", "--tail", "40", name], capture_output=True); log += "\n--- app log ---\n" + tail(lg.stdout + lg.stderr, 2500)
            subprocess.run(["docker", "rm", "-f", name], capture_output=True)
        elif proc:
            try: os.killpg(proc.pid, signal.SIGKILL)
            except Exception: pass
    return dict(code=0 if ok else 1, out=log, secs=round(time.time() - t0, 1), shot=shot)

def run_suite(j, label):
    jid = j["id"]; w = jd(jid) / "work"; stack, plan = make_plan(w, {"start": j["settings"]["start"], "port": j["settings"]["port"]})
    j["stack"] = stack; checks = []; status = {}
    for c in plan:
        j["message"] = f"{label}: running “{c['name']}”"; save(j)
        if c.get("needs") and status.get(c["needs"]) != "passed":
            r = dict(code=-1, out=f"Blocked: {c['needs']} did not pass.", secs=0, shot=""); st = "blocked"
        else:
            r = smoke(jid, c, label) if c.get("kind") == "smoke" else sh(jid, c); st = "passed" if r["code"] == 0 else "failed"
        status[c["id"]] = st
        put_blob(jid, "logs", f"{label}-{c['id']}.txt", f"$ {c['cmd']}\nexit={r['code']}\n\n{r['out']}".encode("utf-8"))
        checks.append(dict(id=c["id"], name=c["name"], status=st, detail=r["out"][-3000:], seconds=r["secs"], screenshot=r.get("shot", ""), cmd=c["cmd"]))
    s = dict(label=label, at=now(), checks=checks); j["suites"].append(s); return s
def bad(s): return [c for c in s["checks"] if c["status"] in ("failed", "blocked")]
def passed(s): return {c["id"] for c in s["checks"] if c["status"] == "passed"}

# ---------- AI diagnosis + patches ----------
SYSTEM = ("You are TestForge's repair engine. Find the ROOT CAUSE of each failing check using ONLY the evidence supplied and fix it with minimal edits. "
          "Return JSON: {\"diagnosis\": str, \"patches\": [{\"path\": str, \"explanation\": str, \"edits\": [{\"search\": str, \"replace\": str}]}]}. "
          "Each 'search' must match the existing file EXACTLY ONCE. For a new file use {\"path\",\"explanation\",\"new_file_content\"}. Never delete files. "
          "Never weaken or delete tests/assertions to make them pass; only change a test if it is demonstrably wrong and say so. "
          "Do not repeat a previously failed or rejected approach (see history). If you cannot fix it from the evidence, return an empty patches list and explain why.")
def ask_ai(payload):
    from .ai import chat, parse_json
    ai = aikey.get_ai()  # the user's own key, entered in Settings (stored encrypted in the database)
    if not ai: return None
    return parse_json(chat(ai, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(payload)[:60000]}], max_tokens=6000, timeout=120, json_mode=True, temperature=0.1))
def gather(w: Path, text: str):
    want = []; allf = {f.relative_to(w).as_posix(): f for f in walk(w)}
    for m in re.findall(r"([\w./\\-]+\.(?:py|js|jsx|ts|tsx|mjs|cjs|json|html|css|vue))", text):
        m = m.replace("\\", "/").lstrip("./")
        for rel in allf:
            if (rel == m or rel.endswith("/" + m)) and rel not in want: want.append(rel)
    want += [r for r in ("package.json", "requirements.txt") if r in allf and r not in want]
    out, tot = {}, 0
    for rel in want[:12]:
        try: s = rd(allf[rel])[:12000]
        except Exception: continue
        if tot + len(s) > 45000: break
        out[rel] = s; tot += len(s)
    return out, sorted(allf)[:150]
def propose(j):
    jid = j["id"]; w = jd(jid) / "work"; n = len(j["iterations"]) + 1
    fails = [c for c in j["current"]["checks"] if c["status"] == "failed"] or bad(j["current"])
    ctx, tree = gather(w, "\n".join(c["detail"] for c in fails))
    hist = [dict(iteration=i["n"], diagnosis=i.get("diagnosis"), outcome=i.get("outcome"), patches=[dict(path=p["path"], explanation=p["explanation"], status=p["status"]) for p in i["patches"]]) for i in j["iterations"]]
    strategy = "Make the smallest safe fix." if n < j["settings"]["max_iterations"] else "FINAL attempt: be conservative; prefer the single most likely root cause."
    it = dict(n=n, diagnosis="", patches=[], outcome="", backup={}, fixed=[], regressions=[], at=now())
    err = ""
    try: resp = ask_ai(dict(iteration=n, strategy=strategy, failing_checks=[dict(id=c["id"], name=c["name"], cmd=c["cmd"], output=c["detail"]) for c in fails], files=ctx, file_tree=tree, history=hist))
    except Exception as e: resp, err = None, str(e)[:200]
    if resp is None:
        it["diagnosis"] = err or "No AI API key is set. Add yours in Settings -> AI provider. Checks ran, but no patches can be proposed."
    else:
        it["diagnosis"] = str(resp.get("diagnosis", ""))[:2000]
        for k, p in enumerate((resp.get("patches") or [])[:8]):
            try:
                rel = str(p["path"]); f = safe(w, rel)
                if any(x in SKIP for x in rel.split("/")): continue
                old = rd(f) if f.is_file() else ""; new = old
                if p.get("edits"):
                    for e in p["edits"]:
                        if not old or new.count(e["search"]) != 1: raise ValueError("search text must match exactly once")
                        new = new.replace(e["search"], e["replace"], 1)
                elif "new_file_content" in p: new = str(p["new_file_content"])
                if new == old or len(new) > 300000: continue
                reason = "modifies a test/spec file" if SENS_TEST.search(rel) else "config / dependency / schema file" if SENS_CFG.search(rel) else ""
                diff = "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), "a/" + rel, "b/" + rel))
                pt = dict(id=f"p{n}-{k}", path=rel, explanation=str(p.get("explanation", ""))[:1500], risk="sensitive" if reason else "low", reason=reason, status="proposed", diff=diff, new_content=new, is_new=not old)
                if j["settings"]["auto_low"] and not reason: pt["status"] = "approved"
                it["patches"].append(pt)
            except Exception as e: it["diagnosis"] += f"\n[discarded invalid patch #{k}: {str(e)[:120]}]"
    j["iterations"].append(it)
    if not it["patches"]: j["status"] = "needs_attention"; j["message"] = "No valid patch could be produced. " + it["diagnosis"][:300]; it["outcome"] = "no_patches"; return False
    return True

# ---------- apply / verify / rollback ----------
def rollback_iter(j, it):
    w = jd(j["id"]) / "work"
    for path, old in it["backup"].items():
        f = safe(w, path)
        if old is None: f.unlink(missing_ok=True)
        else: wr(f, old)
    for p in it["patches"]:
        if p["status"] == "applied": p["status"] = "rolled_back"
    it["backup"] = {}
def verify(j):
    it = j["iterations"][-1]; w = jd(j["id"]) / "work"; n = it["n"]
    for p in it["patches"]:
        if p["status"] == "proposed": p["status"] = "rejected"
    appr = [p for p in it["patches"] if p["status"] == "approved"]
    if not appr:
        it["outcome"] = "no_patches_approved"; j["status"] = "needs_attention"; j["message"] = "All patches were rejected, so nothing was changed. Use Continue to ask the AI for a different approach."; return
    j["status"] = "applying"; save(j)
    for p in appr:
        f = safe(w, p["path"]); it["backup"][p["path"]] = rd(f) if f.is_file() else None; wr(f, p["new_content"]); p["status"] = "applied"
    j["status"] = "verifying"; suite = run_suite(j, f"iter{n}"); prev = j["current"]
    reg, fixed = sorted(passed(prev) - passed(suite)), sorted(passed(suite) - passed(prev)); it["fixed"], it["regressions"] = fixed, reg
    if reg: rollback_iter(j, it); it["outcome"] = "rolled_back_regression"; j["stall"] += 1; return
    j["current"] = suite
    if not bad(suite):
        fin = run_suite(j, "final-regression"); j["current"] = fin
        if not bad(fin): it["outcome"] = "verified"; j["status"] = "verified"; j["message"] = "All applicable checks passed on the verification run and the final regression re-run."; return
        it["outcome"] = "final_rerun_failed"; return
    same = {c["id"] for c in bad(suite)} == {c["id"] for c in bad(prev)} and not fixed
    j["stall"] = j["stall"] + 1 if same else 0; it["outcome"] = "improved" if fixed else "no_progress"
    if j["stall"] >= 2: j["status"] = "stalled"; j["message"] = "Two rounds without progress; stopped instead of looping. Remaining failures are listed in the report."

def cycle(jid, first=False):
    j = load(jid); j["busy"] = True; save(j)
    try:
        if first:
            j["status"] = "analyzing"; s = run_suite(j, "before"); j["current"] = s
            if not s["checks"]: j["status"] = "needs_attention"; j["message"] = "No runnable checks detected. Provide a start command/port or include tests."
            elif not bad(s): j["status"] = "verified"; j["message"] = "No failures found by the configured checks (this is not proof that every feature works)."
        while j["status"] not in TERMINAL and not (first and False):
            last = j["iterations"][-1] if j["iterations"] else None
            if last is None or last["outcome"]:
                if len(j["iterations"]) >= j["settings"]["max_iterations"]:
                    j["status"] = "exhausted"; j["message"] = f"Reached the {j['settings']['max_iterations']}-iteration limit with checks still failing. Nothing was silently marked as fixed."; break
                j["status"] = "diagnosing"; j["message"] = f"Diagnosing (iteration {len(j['iterations']) + 1}/{j['settings']['max_iterations']})"; save(j)
                if not propose(j): break
                if any(p["status"] == "proposed" for p in j["iterations"][-1]["patches"]):
                    j["status"] = "awaiting_approval"; j["message"] = "Review the proposed patches. Nothing is changed until you approve and apply."; break
            verify(j)
    except Exception as e: j["status"] = "failed"; j["message"] = "Engine error: " + str(e)[:300]
    finally:
        j["busy"] = False; save(j)

# ---------- report / export ----------
def report_md(j):
    b = j["suites"][0] if j["suites"] else dict(checks=[]); a = j.get("current") or b; bm = {c["id"]: c for c in b["checks"]}
    v = j["status"] == "verified"; L = [f"# TestForge AI Repair report — {j['name']}", "", f"**Status: {'VERIFIED' if v else 'NOT FULLY VERIFIED (' + j['status'] + ')'}**  ", j["message"], "", f"Stack detected: {', '.join(j['stack']) or 'unknown'}  ", f"Iterations used: {len(j['iterations'])}/{j['settings']['max_iterations']}", "", "## Checks (before → after)", "", "| Check | Before | After |", "|---|---|---|"]
    for c in a["checks"]: L.append(f"| {c['id']} {c['name']} | {bm.get(c['id'], {}).get('status', '-')} | {c['status']} |")
    L += ["", "## Repair history"]
    for it in j["iterations"]:
        L += ["", f"### Iteration {it['n']} — {it['outcome'] or 'pending'}", it["diagnosis"], ""]
        L += [f"- `{p['path']}` [{p['status']}, {p['risk']}] {p['explanation']}" for p in it["patches"]]
        if it["regressions"]: L.append(f"- Regressions caught and rolled back: {', '.join(it['regressions'])}")
    rem = [c for c in a["checks"] if c["status"] != "passed"]
    L += ["", "## Remaining issues / untested", *(["- none among configured checks"] if not rem else [f"- {c['id']} {c['name']}: {c['status']}" for c in rem]),
          "", "Only the checks above were executed. Anything not covered by them is untested.", "", "## Run it", "See `project/` for the corrected source. Install dependencies and use the project's own start script.",
          "", "Evidence: `evidence/shots` (browser screenshots named `<run>-<check>.png`), `evidence/logs` (full command output)."]
    return "\n".join(L)
def build_zip(j):
    d = jd(j["id"]); w = d / "work"; buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in walk(w): z.write(f, "project/" + f.relative_to(w).as_posix())
        for kind, name, data in blobs(j["id"], ("shots", "logs")): z.writestr(f"evidence/{kind}/{name}", data)
        z.writestr("report/REPORT.md", report_md(j)); z.writestr("report/report.json", json.dumps(public(j, True), indent=1))
        for it in j["iterations"]:
            for p in it["patches"]:
                if p["status"] in ("applied", "rolled_back", "approved"): z.writestr(f"patches/iter{it['n']}-{p['id']}-{Path(p['path']).name}.diff", p["diff"])
    return buf.getvalue()

# ---------- API ----------
class Decision(BaseModel):
    decision: str
    edited_content: str | None = None
    confirm_sensitive: bool = False
class Rollback(BaseModel): to_iteration: int = 0

@router.post("", status_code=202)
def create(bg: BackgroundTasks, files: list[UploadFile] = File(default=[]), paths: list[str] = Form(default=[]), git_url: str = Form(""),
           max_iterations: int = Form(5), auto_approve_low_risk: bool = Form(False), start_command: str = Form(""), port: int = Form(0)):
    if not files and not git_url: raise HTTPException(400, "Upload a ZIP, files, a folder, or provide a Git URL.")
    jid = uuid.uuid4().hex; jd(jid).mkdir(parents=True)
    try: ingest(jid, [((paths[i] if i < len(paths) and paths[i] else f.filename or "file"), f.file.read()) for i, f in enumerate(files)], git_url)
    except Exception:
        drop_job(jid); raise
    mi = max(1, min(max_iterations, 10))
    j = dict(id=jid, name=(files[0].filename if files else git_url) or "project", created=now(), status="queued", message="Queued", busy=False, stack=[], stall=0, budget=mi,
             settings=dict(max_iterations=mi, auto_low=auto_approve_low_risk, start=start_command[:300], port=max(0, min(port, 65535)), sandbox=settings().repair_sandbox),
             suites=[], current=None, iterations=[])
    save(j); bg.add_task(cycle, jid, True); return public(j)
@router.get("")
def listing():
    with SessionLocal() as db: rows = db.scalars(select(RepairJob).order_by(RepairJob.updated_at.desc()).limit(30)).all()
    return {"items": [dict(id=r.id, name=r.name, status=r.status, created=r.created_at.isoformat()) for r in rows]}
@router.get("/{jid}")
def get(jid: str): return public(load(jid))
@router.post("/{jid}/patches/{pid}")
def decide(jid: str, pid: str, d: Decision):
    j = load(jid)
    if j["status"] != "awaiting_approval" or j["busy"]: raise HTTPException(409, "Job is not waiting for approval")
    it = j["iterations"][-1]; p = next((x for x in it["patches"] if x["id"] == pid), None)
    if not p: raise HTTPException(404, "Patch not found")
    if d.decision == "reject": p["status"] = "rejected"
    elif d.decision in ("approve", "edit"):
        if p["risk"] == "sensitive" and not d.confirm_sensitive: raise HTTPException(400, f"Sensitive patch ({p['reason']}): explicit confirmation required.")
        if d.edited_content is not None:
            f = safe(jd(jid) / "work", p["path"]); old = rd(f) if f.is_file() else ""
            if len(d.edited_content) > 300000: raise HTTPException(400, "Edited content too large")
            p["new_content"] = d.edited_content; p["edited"] = True
            p["diff"] = "".join(difflib.unified_diff(old.splitlines(True), d.edited_content.splitlines(True), "a/" + p["path"], "b/" + p["path"]))
        p["status"] = "approved"
    else: raise HTTPException(400, "decision must be approve, reject or edit")
    save(j); return public(j)
@router.post("/{jid}/apply", status_code=202)
def apply(jid: str, bg: BackgroundTasks):
    j = load(jid)
    if j["status"] != "awaiting_approval" or j["busy"]: raise HTTPException(409, "Nothing to apply")
    if any(p["status"] == "proposed" for p in j["iterations"][-1]["patches"]): raise HTTPException(400, "Approve or reject every patch first.")
    j["busy"] = True; j["status"] = "applying"; save(j); bg.add_task(cycle, jid); return public(j)
@router.post("/{jid}/continue", status_code=202)
def cont(jid: str, bg: BackgroundTasks):
    j = load(jid)
    if j["busy"] or j["status"] not in ("exhausted", "stalled", "rolled_back", "needs_attention", "failed"): raise HTTPException(409, "Cannot continue from this state")
    last = j["iterations"][-1] if j["iterations"] else None
    if last and not last["outcome"]: rollback_iter(j, last); last["outcome"] = "interrupted"  # undo a half-applied round before retrying
    j["settings"]["max_iterations"] = len(j["iterations"]) + j["budget"]; j["stall"] = 0; j["status"] = "diagnosing"; j["busy"] = True; save(j); bg.add_task(cycle, jid); return public(j)
@router.post("/{jid}/rollback")
def rollback(jid: str, r: Rollback):
    j = load(jid)
    if j["busy"]: raise HTTPException(409, "Job is busy")
    for it in reversed(j["iterations"]):
        if it["n"] > r.to_iteration and it["backup"]: rollback_iter(j, it); it["outcome"] = "rolled_back_manual"
    label = "before" if r.to_iteration == 0 else f"iter{r.to_iteration}"
    j["current"] = next((s for s in reversed(j["suites"]) if s["label"] == label), j["suites"][0]); j["status"] = "rolled_back"
    j["message"] = f"Rolled back to {label}. Use Continue to try again or download the project as it is now."; save(j); return public(j)
@router.get("/{jid}/files/{kind}/{name}")
def files(jid: str, kind: str, name: str):
    jd(jid)
    d = get_blob(jid, kind, name) if kind in ("shots", "logs") else None
    if d is None: raise HTTPException(404, "Not found")
    return Response(d, media_type="image/png" if kind == "shots" else "text/plain")
@router.delete("/{jid}")
def remove(jid: str):
    j = load(jid)
    if j["busy"]: raise HTTPException(409, "Job is still running")
    drop_job(jid); return {"deleted": jid}
@router.get("/{jid}/download")
def download(jid: str):
    j = load(jid)
    if j["busy"]: raise HTTPException(409, "Job is still running")
    tag = "corrected" if j["status"] == "verified" else "partial-unverified"
    return Response(build_zip(j), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="testforge-{tag}-{jid[:8]}.zip"'})
