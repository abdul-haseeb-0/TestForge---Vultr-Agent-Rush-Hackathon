# Production deployment on Vultr

The Blast Radius Zero track requires a Vultr VM backend, Vultr Serverless Inference for agent LLM calls, and isolated execution on Vultr.

## 1. Vultr Serverless Inference

Create a Serverless Inference API key. The OpenAI-compatible API base URL is `https://api.vultrinference.com/v1`; use a bearer token. Put the key only in the backend's environment. The example model is `deepseek-v4.1-flash-1017`; confirm it in the live model catalogue before deployment.

## 2. Isolated worker host

Use a Vultr VX1 Cloud Compute instance with Ubuntu 24.04. Vultr's Microsandbox guide requires CPU virtualization and a usable `/dev/kvm` device. Follow its host setup, install `msb`, verify with `msb doctor`, and install Python SDK `microsandbox`.

Official Vultr guide: https://docs.vultr.com/how-to-set-up-agent-sandboxing-on-vultr-cloud-compute

## 3. Publish the browser OCI image

1. Push this repository to a public GitHub repository.
2. The workflow `.github/workflows/publish-browser-image.yml` builds `worker/Dockerfile.browser` and publishes `ghcr.io/<github-owner>/testforge-browser:latest`.
3. Set `SANDBOX_IMAGE` in `worker/.env` to that exact OCI image reference. Make sure the image is public or authenticate the worker host to GHCR.
4. Verify the image can run with Microsandbox before enabling remote mode.

The image contains Playwright and Chromium. Each scan starts a new microVM and the `async with` lifecycle tears it down after execution. CPU and memory are set in worker environment.

## 4. Start the worker API privately

```bash
cd worker
uv sync
cp .env.example .env
# Set WORKER_TOKEN to a long random value.
# Set SANDBOX_IMAGE=ghcr.io/<github-owner>/testforge-browser:latest
uv run uvicorn app.main:app --host 0.0.0.0 --port 8100
```

Do not expose port 8100 publicly. Allow only the API host/private VPC through the Vultr Firewall.

## 5. Deploy API and frontend

Build frontend:
```bash
cd frontend
npm ci
npm run build
```

Create `backend/.env.production` with:
```dotenv
APP_ENV=production
DATABASE_URL=postgresql+psycopg://testforge:${POSTGRES_PASSWORD}@db:5432/testforge
APP_SECRET_KEY=<python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())">
ARTIFACT_DIR=/app/artifacts
FRONTEND_ORIGINS=https://YOUR_DOMAIN
VULTR_INFERENCE_API_KEY=YOUR_NEW_KEY
VULTR_INFERENCE_BASE_URL=https://api.vultrinference.com/v1
VULTR_INFERENCE_MODEL=deepseek-v4.1-flash-1017
RUNNER_MODE=remote
SANDBOX_WORKER_URL=http://PRIVATE_WORKER_IP:8100
SANDBOX_WORKER_TOKEN=THE_SAME_LONG_RANDOM_VALUE
```

Set `DOMAIN=your-domain.example` in the shell environment before starting Compose. Deploy the API and Caddy frontend using `deploy/docker-compose.production.yml` from a Vultr Cloud Compute host. Point DNS at the Vultr instance; Caddy will obtain and renew TLS certificates automatically. Set `POSTGRES_PASSWORD` in the shell too. Data (runs, findings, repair jobs, screenshots, encrypted API key) lives in the `pgdata` volume; back it up with `pg_dump`. The API has no login yet: put it behind your own auth/VPN before exposing it, because anyone who can reach it can change the AI key.

## 6. Firewall baseline

- Public ingress: TCP 80/443 only; SSH restricted to your IP.
- Worker API: private VPC or firewall allowlist from API host only.
- Database: private only.
- Never expose worker, database, KVM, or runtime management interfaces publicly.

## 7. Required verification before claiming containment

- Run a real scan with `RUNNER_MODE=remote`.
- Confirm worker metadata reports a disposable Microsandbox guest, CPU and memory limits.
- Confirm guest cleanup after normal completion and timeout/failure.
- Attempt access to loopback, RFC1918, link-local, and cloud metadata destinations from a controlled test page. Confirm the microVM runtime blocks non-public destinations and logs the attempt.
- Confirm the inference key is absent from the guest environment.
- Record the actual Vultr-hosted run and containment evidence for the hackathon video.

Microsandbox's default network policy allows public internet access while blocking private, host-local, link-local and metadata destinations. It can be narrowed further with a domain allowlist. The current worker relies on this runtime default plus URL validation in the guest browser runner.
