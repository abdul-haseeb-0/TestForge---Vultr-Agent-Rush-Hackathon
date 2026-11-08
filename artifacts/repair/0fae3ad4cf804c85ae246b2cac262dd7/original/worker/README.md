# TestForge isolated browser worker v1.4.0

The worker API is a private service. It authenticates scan requests and starts a disposable Microsandbox guest. The guest image now contains the same multi-page Playwright scanner used by the local backend and returns per-page screenshots and coverage metadata.

## Build the guest image

The GitHub Actions workflow builds `worker/Dockerfile.browser` from the repository root and publishes the image to GHCR. On the Vultr VM, import/pull the published image into Microsandbox using the current Microsandbox CLI and verify it with a minimal test before connecting the API.

## Run the worker API

```bash
uv sync
cp .env.example .env
# Set WORKER_TOKEN and SANDBOX_IMAGE
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100
```

Do not expose port 8100 publicly. Restrict it to the API host/private VPC. Set `RUNNER_MODE=remote`, `SANDBOX_WORKER_URL`, and the same `SANDBOX_WORKER_TOKEN` on the API host.

## Required Vultr validation

The Microsandbox SDK calls and actual guest lifecycle cannot be proven by a local source review. On the provisioned Vultr KVM host, verify KVM availability, guest image import, one successful execution, timeout behavior, CPU/memory limits, denied private-network egress, guest destruction after success/failure, and worker authentication. Do not claim production containment until these checks pass.
