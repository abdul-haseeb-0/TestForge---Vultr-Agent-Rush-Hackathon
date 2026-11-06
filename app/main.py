import uuid, asyncio, base64, httpx, json
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, HttpUrl, Field
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, inspect, text
from .config import settings
from .db import Base, engine, get_db, SessionLocal
from .models import Run, Finding, Artifact
from .security import validate_url
from .qa import scan, deterministic_report
from .ai import diagnose

cfg=settings(); Base.metadata.create_all(bind=engine)
# Additive SQLite migration for existing v1.3 databases.
try:
    columns = {c["name"] for c in inspect(engine).get_columns("runs")}
    with engine.begin() as conn:
        if "workflow_json" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN workflow_json TEXT NOT NULL DEFAULT '[]'"))
        if "evidence_json" not in columns:
            conn.execute(text("ALTER TABLE runs ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '{}'"))
except Exception:
    # Startup remains explicit: database errors surface on first affected operation.
    pass
app=FastAPI(title="TestForge AI API",version="1.4.0",description="Evidence-based website QA")
app.add_middleware(CORSMiddleware,allow_origins=cfg.origins,allow_credentials=True,allow_methods=["*"],allow_headers=["*"])
class WorkflowStep(BaseModel):
    action: str = Field(pattern="^(navigate|click|fill|select|check|uncheck|assert_visible|assert_hidden|assert_text|assert_text_absent|assert_value|assert_count|assert_url|screenshot)$")
    selector: str = Field(default="", max_length=500)
    value: str = Field(default="", max_length=2000)
class CreateRun(BaseModel):
    target_url: HttpUrl
    depth: str=Field(default="standard",pattern="^(quick|standard|deep)$")
    workflow: list[WorkflowStep] = Field(default_factory=list, max_length=60)
def serialize(row):
    return {"id":row.id,"target_url":row.url,"status":row.status,"created_at":row.created_at,"finished_at":row.finished_at,"summary":row.summary,"score":row.score,"error":row.error,"execution_mode":row.mode,"workflow":json.loads(row.workflow_json or "[]"),"evidence":json.loads(row.evidence_json or "{}"),"findings":[{"id":f.id,"severity":f.severity,"category":f.category,"title":f.title,"description":f.description,"evidence":f.evidence,"recommendation":f.recommendation} for f in row.findings]}
def work(run_id):
    db=SessionLocal(); row=db.get(Run,run_id)
    if not row: db.close(); return
    try:
        row.status="running"; db.commit()
        if cfg.runner_mode == "remote":
            if not cfg.sandbox_worker_url or not cfg.sandbox_worker_token:
                raise RuntimeError("Remote runner selected but SANDBOX_WORKER_URL/TOKEN are not configured.")
            response=httpx.post(cfg.sandbox_worker_url.rstrip("/")+"/execute",
                headers={"Authorization":"Bearer "+cfg.sandbox_worker_token},
                json={"target_url":row.url,"depth":row.depth,"run_id":row.id,"workflow":json.loads(row.workflow_json or "[]")},timeout=cfg.max_run_seconds+20)
            response.raise_for_status(); payload=response.json(); evidence=payload["result"]
            if "pages" not in evidence or "coverage" not in evidence:
                raise RuntimeError("Remote worker returned legacy single-page evidence. Upgrade and verify the Vultr guest image for v1.4 multi-page crawling before using remote mode.")
            artifacts=[]
            folder=cfg.artifacts/row.id; folder.mkdir(parents=True,exist_ok=True)
            screenshots=evidence.pop("screenshots_base64",None) or {}
            legacy_shot=evidence.pop("screenshot_base64",None)
            if legacy_shot and not screenshots:
                screenshots={"homepage.png":legacy_shot}
            for filename, encoded in screenshots.items():
                safe_name=Path(str(filename)).name
                if not safe_name.lower().endswith(".png") or not encoded:
                    continue
                path=folder/safe_name
                path.write_bytes(base64.b64decode(encoded,validate=True))
                artifacts.append((path,"image/png"))
        else:
            evidence,artifacts=asyncio.run(scan(row.url,row.id,row.depth,json.loads(row.workflow_json or "[]")))
        report=deterministic_report(evidence)
        try:
            ai=diagnose(evidence,report)
            if ai:
                # The deterministic browser observations are the source of truth.
                # AI may explain them, but may not invent, delete, or rewrite evidence.
                ai_findings = ai.get("findings") if isinstance(ai.get("findings"), list) else []
                for index, finding in enumerate(report["findings"]):
                    if index >= len(ai_findings) or not isinstance(ai_findings[index], dict):
                        continue
                    explanation = ai_findings[index]
                    if explanation.get("description"):
                        finding["description"] = str(explanation["description"])[:2000]
                    if explanation.get("recommendation"):
                        finding["recommendation"] = str(explanation["recommendation"])[:2000]
                report["summary"] += " AI-assisted explanations were added to observed findings; the evidence and score remain deterministic."
            else:
                report["summary"] += " AI diagnosis unavailable: configure a Vultr inference key."
        except Exception as e: report["summary"] += f" AI diagnosis failed: {str(e)[:180]}"
        row.summary=report["summary"]; row.score=report["score"]; row.evidence_json=json.dumps(evidence, default=str)
        for f in report["findings"]: db.add(Finding(run_id=row.id,**f))
        for p,ctype in artifacts: db.add(Artifact(run_id=row.id,filename=p.name,path=str(p)))
        row.status="completed"; row.finished_at=datetime.now(timezone.utc); db.commit()
    except Exception as e:
        db.rollback(); row=db.get(Run,run_id)
        if row: row.status="failed"; row.error=str(e)[:2000]; row.finished_at=datetime.now(timezone.utc); db.commit()
    finally: db.close()
@app.get("/api/health")
def health(): return {"status":"ok","service":"testforge-api","version":"1.4.0"}
@app.get("/api/config")
def config(): return {"ai_configured":bool(cfg.vultr_inference_api_key),"runner_mode":cfg.runner_mode,"production_sandbox_configured":bool(cfg.sandbox_worker_url and cfg.sandbox_worker_token)}
@app.post("/api/runs",status_code=202)
def create(payload:CreateRun,bg:BackgroundTasks,db:Session=Depends(get_db)):
    url=validate_url(str(payload.target_url)); row=Run(id=str(uuid.uuid4()),url=url,depth=payload.depth,workflow_json=json.dumps([x.model_dump() for x in payload.workflow]),status="queued",mode=cfg.runner_mode,summary="Queued for multi-page browser execution.")
    db.add(row); db.commit(); db.refresh(row); bg.add_task(work,row.id); return serialize(row)
@app.get("/api/runs")
def runs(limit:int=25,db:Session=Depends(get_db)):
    rows=db.scalars(select(Run).options(selectinload(Run.findings)).order_by(Run.created_at.desc()).limit(max(1,min(limit,100)))).all()
    return {"items":[serialize(x) for x in rows]}
@app.get("/api/runs/{run_id}")
def run(run_id:str,db:Session=Depends(get_db)):
    row=db.scalar(select(Run).options(selectinload(Run.findings)).where(Run.id==run_id))
    if not row: raise HTTPException(404,"Run not found")
    return serialize(row)
@app.get("/api/runs/{run_id}/artifacts")
def artifacts(run_id:str,db:Session=Depends(get_db)):
    if not db.get(Run,run_id): raise HTTPException(404,"Run not found")
    rows=db.scalars(select(Artifact).where(Artifact.run_id==run_id)).all()
    return {"items":[{"filename":x.filename,"url":f"/api/artifacts/{x.id}"} for x in rows]}
@app.get("/api/artifacts/{artifact_id}")
def artifact(artifact_id:int,db:Session=Depends(get_db)):
    x=db.get(Artifact,artifact_id)
    if not x: raise HTTPException(404,"Artifact not found")
    p=Path(x.path).resolve()
    if cfg.artifacts not in p.parents or not p.is_file(): raise HTTPException(404,"Artifact missing")
    return FileResponse(p,media_type="image/png",filename=x.filename)
@app.get("/api/runs/{run_id}/report")
def report(run_id:str,db:Session=Depends(get_db)):
    x=db.get(Run,run_id)
    if not x: raise HTTPException(404,"Run not found")
    return {"id":x.id,"url":x.url,"status":x.status,"score":x.score,"summary":x.summary,"error":x.error,"mode":x.mode,"evidence":json.loads(x.evidence_json or "{}"),"findings":[{"id":f.id,"severity":f.severity,"category":f.category,"title":f.title,"description":f.description,"evidence":f.evidence,"recommendation":f.recommendation} for f in x.findings]}
