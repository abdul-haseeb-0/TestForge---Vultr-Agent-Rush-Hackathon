# TestForge AI architecture v1.4.0

```text
React + Vite frontend
        |
        | /api (Vite dev proxy)
        v
FastAPI backend ---- SQLite / PostgreSQL
        |
        +---- Playwright multi-page scanner (local development)
        |       +---- same-origin rendered-link crawler
        |       +---- per-page screenshots and findings
        |       +---- explicit user-defined CRUD workflows
        |
        +---- Vultr Serverless Inference (optional explanations)
        |
        +---- private worker API (remote mode)
                |
                v
          Microsandbox disposable guest
                +---- same v1.4 scanner package
                +---- Chromium / Playwright
                +---- screenshot artifacts returned to API
```

The deterministic browser observations, page coverage, and test assertions are authoritative. The LLM may explain observed findings but must not invent test evidence or alter the deterministic score.

The crawler is bounded by depth/page count and a run-time budget. It follows same-origin links found in rendered anchors. User-authored workflows supply application-specific CRUD selectors and assertions. Automatic scans remain read-only.

Local mode is for development. Remote mode is only a production security boundary after the actual Vultr VM, Microsandbox guest lifecycle, CPU/memory constraints, network egress rules, worker authentication, and teardown have been verified.
