# AI Repair & Verification (v1.5)

Sequence: Upload -> Baseline checks (sandbox) -> AI diagnosis -> Patch proposals -> **Human approval** -> Apply -> Re-run checks -> Regression guard -> Loop (max N) -> Final regression re-run -> Export.

* Input: ZIP, loose files, folder, or public Git URL (`POST /api/repair`, multipart).
* Sandbox: `REPAIR_SANDBOX=docker` (default): `--cap-drop ALL`, 1 GB RAM, 1 CPU, pids limit, no network except dependency install and the app smoke test (published port needs a bridge network; use a dedicated VM for hostile code). `process` mode is NOT isolated and needs `REPAIR_ALLOW_UNSAFE_PROCESS=true`.
* Checks (auto-detected): dependency install (scripts disabled), build, unit tests, syntax/compile, app start + Playwright screenshot + console/page errors. Set a start command/port in the form for backends or custom apps.
* Loop safety: max iterations (default 5, cap 10); a round that breaks a passing check is rolled back; 2 rounds with no progress = stop; "verified" requires a clean verify run AND a clean final re-run.
* Approval: AI never writes files. Config/dependency/schema/test-file patches need an extra confirmation; optional auto-approve applies to low-risk patches only.
* Output zip: `project/`, `report/REPORT.md|json`, `evidence/shots|logs`, `patches/*.diff`. Unverified jobs download as "partial-unverified".
* Not covered yet: DB schema/CRUD destructive tests, Java/PHP checks, multi-user auth on job endpoints.
