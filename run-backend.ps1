Set-Location "$PSScriptRoot/backend"
if (!(Test-Path .env)) { Copy-Item .env.example .env }
uv sync
uv run playwright install chromium
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
