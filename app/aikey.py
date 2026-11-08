"""User-supplied AI provider settings, entered in the UI and stored in PostgreSQL.
The API key is encrypted at rest (Fernet) and is never returned by any endpoint."""
from __future__ import annotations
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from cryptography.fernet import Fernet, InvalidToken
from .config import settings
from .db import SessionLocal
from .models import AppSetting
from .security import validate_url

router = APIRouter(prefix="/api/settings", tags=["settings"])

def _fernet() -> Fernet:
    cfg = settings()
    if cfg.app_secret_key: return Fernet(cfg.app_secret_key.encode())
    f = cfg.artifacts / ".fernet.key"  # dev convenience; set APP_SECRET_KEY in production (generate: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
    if not f.exists(): f.write_bytes(Fernet.generate_key()); os.chmod(f, 0o600)
    return Fernet(f.read_bytes())
def _get(db, k): r = db.get(AppSetting, k); return r.value if r else ""
def _put(db, k, v):
    r = db.get(AppSetting, k)
    if r: r.value, r.updated_at = v, datetime.now(timezone.utc)
    else: db.add(AppSetting(key=k, value=v))

def get_ai():
    """-> {key, base_url, model} or None. The UI-stored key wins; env var is only a fallback."""
    cfg = settings()
    with SessionLocal() as db: enc, url, model = _get(db, "ai_api_key"), _get(db, "ai_base_url"), _get(db, "ai_model")
    key = ""
    if enc:
        try: key = _fernet().decrypt(enc.encode()).decode()
        except InvalidToken: key = ""  # secret changed: user must re-enter the key
    key = key or cfg.vultr_inference_api_key
    return {"key": key, "base_url": url or cfg.vultr_inference_base_url, "model": model or cfg.vultr_inference_model} if key else None

class AiIn(BaseModel):
    api_key: str | None = None  # None/empty = keep the stored key
    base_url: str = ""
    model: str = ""

def _status():
    ai = get_ai()
    with SessionLocal() as db: stored = bool(_get(db, "ai_api_key"))
    cfg = settings()
    return {"configured": bool(ai), "last4": ai["key"][-4:] if ai else "", "source": "ui" if stored and ai else "env" if ai else "",
            "base_url": (ai or {}).get("base_url") or cfg.vultr_inference_base_url, "model": (ai or {}).get("model") or cfg.vultr_inference_model}

@router.get("/ai")
def read(): return _status()
@router.put("/ai")
def write(b: AiIn):
    url = b.base_url.strip().rstrip("/")
    if url:
        if not url.startswith(("https://", "http://")): raise HTTPException(400, "Base URL must start with https://")
        if not settings().ai_allow_private_url: validate_url(url)  # blocks localhost/private ranges (SSRF)
    key = (b.api_key or "").strip()
    if key and (len(key) < 8 or len(key) > 400 or any(c.isspace() for c in key)): raise HTTPException(400, "That does not look like an API key.")
    with SessionLocal() as db:
        if key: _put(db, "ai_api_key", _fernet().encrypt(key.encode()).decode())
        _put(db, "ai_base_url", url); _put(db, "ai_model", b.model.strip()[:120]); db.commit()
    return _status()
@router.delete("/ai")
def remove():
    with SessionLocal() as db: _put(db, "ai_api_key", ""); db.commit()
    return _status()
@router.post("/ai/test")
def test():
    ai = get_ai()
    if not ai: raise HTTPException(400, "No API key configured.")
    try:
        from openai import OpenAI
        r = OpenAI(base_url=ai["base_url"], api_key=ai["key"], timeout=30, max_retries=0).chat.completions.create(model=ai["model"], messages=[{"role": "user", "content": "Reply with: ok"}], max_completion_tokens=8)
        return {"ok": True, "message": "Connected. Model replied: " + (r.choices[0].message.content or "").strip()[:40]}
    except Exception as e:
        return {"ok": False, "message": str(e).replace(ai["key"], "***")[:300]}
