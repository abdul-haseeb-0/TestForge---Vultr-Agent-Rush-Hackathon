from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./testforge.db"
    frontend_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    artifact_dir: str = "./artifacts"
    vultr_inference_api_key: str = ""
    vultr_inference_base_url: str = "https://api.vultrinference.com/v1"
    vultr_inference_model: str = "deepseek-v4.1-flash-1017"
    runner_mode: str = "local"
    sandbox_worker_url: str = ""
    sandbox_worker_token: str = ""
    max_run_seconds: int = 90
    repair_sandbox: str = "docker"  # docker | process (process = NOT isolated, dev only)
    repair_allow_unsafe_process: bool = False
    repair_max_upload_mb: int = 100
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    @property
    def origins(self): return [x.strip() for x in self.frontend_origins.split(",") if x.strip()]
    @property
    def artifacts(self):
        p = Path(self.artifact_dir).resolve(); p.mkdir(parents=True, exist_ok=True); return p

@lru_cache
def settings(): return Settings()
