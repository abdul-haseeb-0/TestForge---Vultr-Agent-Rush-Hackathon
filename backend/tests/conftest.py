import os, tempfile
_tmp = tempfile.mkdtemp(prefix="tf-test-")
# Must be set before `app` is imported: settings/engine are created at import time.
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["ARTIFACT_DIR"] = f"{_tmp}/artifacts"
os.environ["VULTR_INFERENCE_API_KEY"] = ""   # never use a real key in tests
os.environ["APP_SECRET_KEY"] = ""
os.environ["SETTINGS_ADMIN_TOKEN"] = ""
os.environ["REPAIR_SANDBOX"] = "process"
os.environ["REPAIR_ALLOW_UNSAFE_PROCESS"] = "true"
