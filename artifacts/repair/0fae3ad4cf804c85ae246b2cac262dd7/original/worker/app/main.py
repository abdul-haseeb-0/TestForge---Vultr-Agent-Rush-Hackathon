import os, secrets, asyncio, json, base64, uuid
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, HttpUrl, Field
from microsandbox import Sandbox

app=FastAPI(title="TestForge Isolated Worker",version="1.4.0")
TOKEN=os.getenv("WORKER_TOKEN",""); IMAGE=os.getenv("SANDBOX_IMAGE","testforge-browser:latest")
CPUS=int(os.getenv("SANDBOX_CPUS","1")); MEMORY=int(os.getenv("SANDBOX_MEMORY_MB","768")); TIMEOUT=int(os.getenv("SANDBOX_TIMEOUT_SECONDS","90"))
class WorkflowStep(BaseModel):
    action: str=Field(pattern="^(navigate|click|fill|select|check|uncheck|assert_visible|assert_hidden|assert_text|assert_text_absent|assert_value|assert_count|assert_url|screenshot)$")
    selector: str=Field(default="",max_length=500)
    value: str=Field(default="",max_length=2000)
class Task(BaseModel):
    target_url: HttpUrl
    depth: str=Field(default="standard",pattern="^(quick|standard|deep)$")
    run_id: str=Field(default_factory=lambda:str(uuid.uuid4()))
    workflow: list[WorkflowStep]=Field(default_factory=list,max_length=60)
@app.get("/health")
def health(): return {"status":"ok","sandbox_provider":"microsandbox","image":IMAGE}
@app.post("/execute")
async def execute(task:Task,authorization:str|None=Header(default=None)):
    supplied=(authorization or "").removeprefix("Bearer ").strip()
    if not TOKEN or not secrets.compare_digest(supplied,TOKEN): raise HTTPException(401,"Unauthorized")
    data=base64.b64encode(json.dumps(task.model_dump(mode="json")).encode()).decode()
    command="import base64,json,subprocess,sys; p=json.loads(base64.b64decode('"+data+"')); r=subprocess.run(['python','/opt/testforge/run_scan.py',json.dumps(p)],capture_output=True,text=True,timeout=80); print(r.stdout); print(r.stderr,file=sys.stderr); sys.exit(r.returncode)"
    try:
        async with await Sandbox.create("tf-"+task.run_id[:10],image=IMAGE,cpus=CPUS,memory=MEMORY,replace=True) as box:
            result=await asyncio.wait_for(box.exec("python",["-c",command]),timeout=TIMEOUT)
            if result.exit_code!=0: raise RuntimeError((result.stderr_text or "sandbox failed")[:600])
            return {"run_id":task.run_id,"sandbox":{"provider":"microsandbox","disposable":True,"cpus":CPUS,"memory_mb":MEMORY,"destroyed_after_run":True},"result":json.loads(result.stdout_text)}
    except Exception as exc: raise HTTPException(502,"Isolated execution failed: "+str(exc)[:500])
