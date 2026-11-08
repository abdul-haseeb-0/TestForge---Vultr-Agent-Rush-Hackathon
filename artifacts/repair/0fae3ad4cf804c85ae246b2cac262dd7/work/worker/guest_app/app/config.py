from pathlib import Path
import os
class GuestSettings:
    max_run_seconds = int(os.getenv("MAX_RUN_SECONDS", "90"))
    @property
    def artifacts(self):
        path = Path(os.getenv("ARTIFACT_DIR", "/tmp/testforge-artifacts")).resolve()
        path.mkdir(parents=True, exist_ok=True)
        return path
def settings(): return GuestSettings()
