# v1.4.0 engineering review

## Changes in this release

- Replaced the single-page scan with a bounded same-origin crawler that navigates to each discovered page in Chromium.
- Captures full-page and viewport screenshots for each visited page and associates findings with the page screenshot.
- Reports discovered pages, visited pages, page cap, crawl truncation, and observed forms.
- Adds a run-time budget to prevent deep crawls from running without a bound.
- Keeps automatic scans read-only. It does not auto-submit forms or automatically trigger destructive actions.
- Adds explicit, user-authored browser workflow steps for CRUD testing: navigation, click, fill, select, check/uncheck, visibility/text/value/count/URL assertions, and screenshots.
- Persists workflow definitions and browser evidence; includes additive database migration for existing SQLite/PostgreSQL runs tables.
- Adds page coverage and workflow results to the dashboard.
- Adds coverage-aware scoring: no visited page means no quality score; a truncated crawl caps the score at 85.
- Keeps third-party 401/403/429 observations informational and groups repeated HTTP failures.
- Updates the disposable browser guest image to run the same v1.4.0 scanner code and return page screenshots as artifacts.
- Rejects legacy remote-worker responses that do not contain multi-page coverage evidence rather than silently presenting them as complete.

## Validation performed in this build environment

- Backend Python compilation: passed.
- Backend unit tests: 15 passed.
- FastAPI TestClient smoke checks for `/api/health`, `/api/config`, and `/api/runs`: HTTP 200.
- Frontend TSX transpilation/syntax diagnostics: zero.
- Worker and guest Python compilation: passed.
- Full frontend dependency install and Vite production build: not completed in this environment because `npm install` timed out. Run `npm install` and `npm run build` on the development PC before deployment.
- Real Chromium end-to-end crawl against a controlled multi-page test site: not executed in this environment because the Playwright browser binary was not installed.
- Microsandbox SDK lifecycle, guest image import, KVM availability, network isolation, and teardown on the Vultr VM: not verified here. Validate on the actual Vultr host before claiming isolated production execution.

## Known product boundaries

- Automatic crawling follows rendered same-origin anchor links. It cannot guarantee discovery of every SPA state, authenticated route, infinite-scroll item, or page that requires a business-specific interaction.
- CRUD testing requires explicit selectors and expected values for the target application. A universal crawler cannot safely infer the semantics of every create/update/delete operation.
- Automatic mode does not submit forms or mutate application data. User-authored workflows can mutate data and must only be used against authorized staging/test environments.
- Local Windows browser execution is development mode, not a security boundary for untrusted code.
- A clean report means no defects were detected by the configured checks on the pages/actions actually tested. It is not a guarantee that a website is defect-free.
