"""User-supplied AI provider settings, entered in the UI and stored in the database.
The API key is encrypted at rest (Fernet) and is never returned by any endpoint."""
from __future__ import annotations
import os, secrets, threading
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from cryptography.fernet import Fernet, InvalidToken
from .config import settings
from .db import SessionLocal
from .models import AppSetting
from .security import validate_url

_key_lock = threading.Lock()

def require_admin(x_admin_token: str = Header(default="")):
    """Optional protection: if SETTINGS_ADMIN_TOKEN is set, callers must send it."""
    want = settings().settings_admin_token
    if want and not secrets.compare_digest(x_admin_token.encode(), want.encode()):
        raise HTTPException(401, "Invalid or missing X-Admin-Token.")

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_admin)])

def _fernet() -> Fernet:
    cfg = settings()
    if cfg.app_secret_key:
        try: return Fernet(cfg.app_secret_key.encode())
        except Exception: raise HTTPException(500, "APP_SECRET_KEY is not a valid Fernet key. Generate one with: python -c \"from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())\"")
    f = cfg.artifacts / ".fernet.key"  # dev convenience; set APP_SECRET_KEY in production
    with _key_lock:
        if not f.exists():
            tmp = f.with_suffix(".tmp"); tmp.write_bytes(Fernet.generate_key()); os.chmod(tmp, 0o600); os.replace(tmp, f)
    return Fernet(f.read_bytes())

def _get(db, k): r = db.get(AppSetting, k); return r.value if r else ""
def _put(db, k, v):
    r = db.get(AppSetting, k)
    if r: r.value, r.updated_at = v, datetime.now(timezone.utc)
    else: db.add(AppSetting(key=k, value=v, updated_at=datetime.now(timezone.utc)))

def get_ai():
    """-> {key, base_url, model} or None. The UI-stored key wins; the env var is only a fallback."""
    cfg = settings()
    with SessionLocal() as db: enc, url, model = _get(db, "ai_api_key"), _get(db, "ai_base_url"), _get(db, "ai_model")
    key = ""
    if enc:
        try: key = _fernet().decrypt(enc.encode()).decode()
        except InvalidToken: key = ""  # secret changed: user must re-enter the key
    from_ui = bool(key)
    key = key or cfg.vultr_inference_api_key
    if not key: return None
    # Custom URL/model only apply together with a UI key; the env key keeps its own env URL/model.
    return {"key": key, "from_ui": from_ui,
            "base_url": (url if from_ui and url else cfg.vultr_inference_base_url),
            "model": (model if from_ui and model else cfg.vultr_inference_model)}

class AiIn(BaseModel):
    api_key: str | None = None  # None/empty = keep the stored key
    base_url: str = ""
    model: str = ""

def _status():
    ai = get_ai(); cfg = settings()
    return {"configured": bool(ai), "last4": ai["key"][-4:] if ai else "", "source": ("ui" if ai["from_ui"] else "env") if ai else "",
            "base_url": ai["base_url"] if ai else cfg.vultr_inference_base_url, "model": ai["model"] if ai else cfg.vultr_inference_model}

@router.get("/ai")
def read(): return _status()

@router.put("/ai")
def write(b: AiIn):
    url = b.base_url.strip().rstrip("/")
    if url:
        if not url.startswith(("https://", "http://")): raise HTTPException(400, "Base URL must start with https:// or http://")
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
        from .ai import chat
        out = chat(ai, [{"role": "user", "content": "Reply with: ok"}], max_tokens=16, timeout=30, retries=0)
        return {"ok": True, "message": "Connected. Model replied: " + out.strip()[:40]}
    except Exception as e:
        return {"ok": False, "message": str(e).replace(ai["key"], "***")[:300]}
