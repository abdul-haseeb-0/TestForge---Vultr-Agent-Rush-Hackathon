# TestForge AI v1.4.0

**Multi-page website QA with browser evidence, page coverage, and user-defined CRUD/workflow scenarios.**

## Local Windows setup

Keep two PowerShell terminals open. Run both from the extracted project folder.

### 1. Backend

```powershell
cd backend
uv sync
if (!(Test-Path .env)) { Copy-Item .env.example .env }
uv run playwright install chromium
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API health: http://127.0.0.1:8000/api/health  
Interactive API docs: http://127.0.0.1:8000/docs

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. Frontend and backend are independent projects and processes. Docker is not required for local Windows development.

## Configure Vultr inference

Edit `backend/.env` and add your own key:

```dotenv
VULTR_INFERENCE_API_KEY=YOUR_NEW_KEY
VULTR_INFERENCE_BASE_URL=https://api.vultrinference.com/v1
VULTR_INFERENCE_MODEL=deepseek-v4.1-flash-1017
```

Never place this key in frontend code or commit it. Deterministic browser testing works without the inference key; AI explanations do not.

## What the scanner does

- Opens the submitted website in real Chromium using Playwright.
- Crawls same-origin internal links by actually navigating to each discovered page.
- Captures full-page and viewport screenshots for every visited page.
- Shows discovered/visited page coverage and whether the configured page limit truncated the crawl.
- Collects page-associated console errors, HTTP responses, request failures, and document navigation failures.
- Groups duplicate HTTP observations and treats access restrictions and third-party responses as informational rather than confirmed app defects.
- Observes forms and their fields without submitting them automatically.
- Runs limited safe button smoke tests without submitting forms or automatically triggering destructive/payment actions.
- Supports explicit, ordered browser workflows for CRUD testing in a dedicated staging environment.
- Stores page evidence and screenshots with each run and exports machine-readable reports.

### Crawl limits

- Quick: up to 3 pages.
- Standard: up to 12 pages.
- Deep: up to 30 pages.

The crawler follows links discoverable in rendered HTML on the same origin. It cannot guarantee discovery of every route, hidden SPA state, authenticated page, infinite-scroll item, or page reachable only after a specific business workflow. A page-limit warning means coverage is incomplete. No scanner can honestly promise that every page on every website was tested automatically.

## Explicit CRUD / workflow testing

Automatic mode is read-only. For CRUD, open **Advanced: test a CRUD workflow** and provide an ordered JSON array. Workflows may mutate website data, so use an authorized staging/test environment and dedicated test records only.

Supported actions:

- `navigate` with `value` as a same-origin path or URL.
- `click`, `fill`, `select`, `check`, `uncheck` with `selector`; `fill` and `select` also use `value`.
- `assert_visible` with `selector`.
- `assert_hidden` with `selector`.
- `assert_text` / `assert_text_absent` with `selector` and expected `value`.
- `assert_value` for input values, and `assert_count` for selector counts.
- `assert_url` with expected URL substring in `value`.
- `screenshot` to capture the current state.

Example scenario (adapt selectors and routes to the target application):

```json
[
  {"action":"navigate","value":"/items"},
  {"action":"click","selector":"[data-testid='add-item']"},
  {"action":"fill","selector":"input[name='name']","value":"TestForge QA record"},
  {"action":"click","selector":"button[type='submit']"},
  {"action":"assert_text","selector":"body","value":"TestForge QA record"},
  {"action":"navigate","value":"/items"},
  {"action":"assert_text","selector":"body","value":"TestForge QA record"},
  {"action":"click","selector":"[data-testid='edit-testforge-record']"},
  {"action":"fill","selector":"input[name='name']","value":"TestForge QA record updated"},
  {"action":"click","selector":"button[type='submit']"},
  {"action":"assert_text","selector":"body","value":"TestForge QA record updated"},
  {"action":"click","selector":"[data-testid='delete-testforge-record']"},
  {"action":"click","selector":"[data-testid='confirm-delete']"},
  {"action":"assert_text_absent","selector":"body","value":"TestForge QA record updated"}
]
```

To test full CRUD, add the application's real edit and delete actions plus assertions after each operation. TestForge does not invent business-specific selectors or decide which production records are safe to delete. Each step gets a screenshot and pass/fail record.

## API

- `GET /api/health`
- `GET /api/config`
- `POST /api/runs` with `target_url`, `depth`, and optional `workflow` array.
- `GET /api/runs`
- `GET /api/runs/{id}` including page evidence and workflow results.
- `GET /api/runs/{id}/artifacts`
- `GET /api/artifacts/{artifact_id}`
- `GET /api/runs/{id}/report`

## Security and deployment

Local Windows execution is for development and is not a security boundary for arbitrary uploaded code. The URL validator blocks private and reserved addresses and browser requests are revalidated, but production deployments still need network-level egress controls to mitigate DNS rebinding and SSRF. Do not expose the worker, database, sandbox control socket, or container runtime publicly. Verify the Microsandbox SDK, guest image, limits, network policy, and teardown on your Vultr host before claiming isolated production execution.

## Tests

```powershell
cd backend
uv run pytest
```

MIT License. See `LICENSE`.

## Using your own AI API key
Open the app → **Settings** → *AI provider (your own API key)*. Paste a key for any OpenAI-compatible provider
(Vultr, OpenAI, OpenRouter, or your own base URL + model), press **Save**, then **Test connection**.
The key is encrypted (Fernet) in the database and is never returned by the API. The same key powers scan
explanations and AI Repair patches. For production set `APP_SECRET_KEY` and `SETTINGS_ADMIN_TOKEN`
(the Settings page will then ask for the token) in `backend/.env`.

## Tests
`cd backend && uv run pytest` — 34 tests (API-key handling, scanner against a local buggy site, DB-backed AI Repair loop).
`cd frontend && npm run build` — type-checks and builds the UI.
