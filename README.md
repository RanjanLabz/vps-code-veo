# Distributed Flow Orchestration Platform

Production-oriented Google Flow / FlowKit orchestration system with a global FastAPI orchestrator, external Redis-backed queues, MongoDB state store, Cloudflare R2 media storage, and multi-account VPS worker nodes.

## What It Provides

- One isolated Chrome profile per account.
- Visible Chrome sessions under Xvfb + Fluxbox.
- Per-account x11vnc debug ports.
- Optional per-account proxy.
- FlowKit-compatible Chrome extension bridge per account.
- Runtime global Flow model/duration/credit configuration shared by all accounts.
- Redis-backed job queue with active, delayed, retry, and completed job state.
- FastAPI account and job management API.
- Recovery engine for reconnecting Playwright, clearing `labs.google` storage, refreshing Flow, and restarting Chrome.
- Docker Compose deployment with external Redis and auto-start on reboot.
- Global orchestrator API on port `8090`.
- Global capacity manager that selects the healthiest VPS worker.
- MongoDB collections for jobs, workers, accounts, settings, logs, and metrics.
- Cloudflare R2 bucket configuration for generated media storage.
- Next.js internal admin/testing panel under `frontend/`.

## Repository Layout

This working tree contains the full platform for local development:

- `orchestrator/`: global FastAPI scheduler, global queue, worker registry, capacity logic.
- `worker/`: VPS browser appliance API, account manager, Chrome/VNC/FlowKit bridge, local queue.
- `extension/`: FlowKit-compatible Chrome extension loaded into each account profile.
- `frontend/`: admin/testing UI.
- `config/`: default YAML only. Runtime worker/VPS records are stored in the database.
- `docker/`, `docker-compose*.yml`: local/VPS container entrypoints.
- `scripts/`: install/update/registration helpers.
- `terraform/`: optional Oracle provisioning. Terraform state should stay local and is gitignored.

Separate deployment repos can contain only the relevant subset. For example,
`flowkit-global-orchestrator` should contain only `orchestrator/`, its config,
Render Dockerfile, requirements, and deployment metadata.

## Quick Install

On a fresh Ubuntu 22.04+ VPS:

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | REPO_URL=https://github.com/<owner>/<repo>.git bash
```

External Redis is required:

```bash
export REDIS_URL="redis://default:password@host:port"
export ORCHESTRATOR_REDIS_URL="$REDIS_URL"
export MONGODB_URI="mongodb+srv://user:password@cluster.mongodb.net/?appName=FlowAPI"
export MONGODB_DATABASE="flowkit_orchestrator"
export R2_ENDPOINT_URL="https://account-id.r2.cloudflarestorage.com"
export R2_BUCKET="flowkit-generated-media"
export R2_ACCESS_KEY_ID="..."
export R2_SECRET_ACCESS_KEY="..."
```

For a local checkout on the VPS:

```bash
sudo APP_DIR=/opt/flow-worker ./scripts/install.sh
```

The installer installs Docker and Chrome, creates persistent directories, builds the worker container, starts Compose, and installs a systemd unit.

## New VPS From GitHub

1. Push this repository to GitHub.
2. On every new VPS, run:

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | REPO_URL=https://github.com/<owner>/<repo>.git bash
```

This clones the repo into `/opt/flow-worker`, installs Docker and Chrome, starts the orchestrator and the worker, and enables auto-start on reboot. Redis, MongoDB, and R2 are expected to be cloud/external services supplied through `.env` or environment variables.

To auto-register the VPS with a remote orchestrator during install, pass:

```bash
ORCHESTRATOR_URL="https://flowkit-global-orchestrator.onrender.com" \
ORCHESTRATOR_API_KEY="..." \
WORKER_ID="vps-1" \
WORKER_PUBLIC_URL="http://YOUR_ORACLE_PUBLIC_IP:8080" \
curl -fsSL https://raw.githubusercontent.com/<owner>/<repo>/main/install.sh | REPO_URL=https://github.com/<owner>/<repo>.git bash
```

If `WORKER_PUBLIC_URL` is omitted, the installer attempts to detect the public IP.

To update an existing VPS:

```bash
cd /opt/flow-worker
sudo bash ./scripts/update.sh
```

## Runtime Ports

- Orchestrator API: `8090`
- Worker API: `8080`
- VNC accounts: `5901-5999`
- Chrome remote debugging inside container: `9222-9322`

## API Examples

Create an account:

```bash
curl -X POST http://localhost:8080/accounts \
  -H 'content-type: application/json' \
  -d '{"id":"acc-1","proxy_enabled":false}'
```

Create an account with a proxy:

```bash
curl -X POST http://localhost:8080/accounts \
  -H 'content-type: application/json' \
  -d '{"id":"acc-2","proxy_enabled":true,"proxy_url":"http://user:pass@host:8080"}'
```

Submit a job:

```bash
curl -X POST http://localhost:8080/jobs \
  -H 'content-type: application/json' \
  -d '{"prompt":"Create a short cinematic clip of a city at sunrise"}'
```

Read global Flow settings from the orchestrator:

```bash
curl http://localhost:8090/flow-settings
```

Update the universal model/cost used by all accounts:

```bash
curl -X PATCH http://localhost:8090/flow-settings \
  -H 'content-type: application/json' \
  -d '{
    "text_to_video": {
      "model": "veo-3.1-fast",
      "duration": 8,
      "estimated_credits": 160
    }
  }'
```

Submit a generation request using the global settings:

```bash
curl -X POST https://flowkit-global-orchestrator.onrender.com/generate/text-to-video \
  -H 'content-type: application/json' \
  -H 'x-api-key: <orchestrator-api-key>' \
  -d '{"prompt":"cinematic Tokyo rain street","aspect_ratio":"16:9"}'
```

Image-to-image and image-to-video jobs require an input image. Send one of
`inputs.image_url`, `inputs.image_data_url`, or `inputs.image_media_id`.
Use `caption` for the edit/reference instruction and `aspect_ratio` for output
size (`16:9`, `9:16`, or `1:1`):

```bash
curl -X POST https://flowkit-global-orchestrator.onrender.com/generate/image-to-image \
  -H 'content-type: application/json' \
  -H 'x-api-key: <orchestrator-api-key>' \
  -d '{
    "prompt": "turn this product photo into a cinematic ad frame",
    "caption": "Preserve the product shape and logo, change the background to neon Tokyo rain.",
    "aspect_ratio": "16:9",
    "inputs": {
      "image_url": "https://example.com/input.png"
    }
  }'
```

Register another VPS worker with the orchestrator:

```bash
curl -X POST http://localhost:8090/workers \
  -H 'content-type: application/json' \
  -d '{"id":"vps-2","base_url":"http://10.0.0.20:8080","max_jobs":10}'
```

Worker URLs are persisted in MongoDB/PostgreSQL through the orchestrator API. They
are no longer written back into YAML. If Oracle changes a VPS IP, update the
worker record instead of editing environment variables:

```bash
curl -X POST https://flowkit-global-orchestrator.onrender.com/workers \
  -H 'content-type: application/json' \
  -H 'x-api-key: <orchestrator-api-key>' \
  -d '{"id":"vps-1","base_url":"http://NEW_ORACLE_IP:8080","enabled":true,"max_jobs":10,"weight":100}'
```

Remove a VPS from scheduling:

```bash
curl -X DELETE https://flowkit-global-orchestrator.onrender.com/workers/vps-1 \
  -H 'x-api-key: <orchestrator-api-key>'
```

Or run the helper from a VPS:

```bash
cd /opt/flow-worker
ORCHESTRATOR_URL="https://flowkit-global-orchestrator.onrender.com" \
ORCHESTRATOR_API_KEY="..." \
WORKER_PUBLIC_URL="http://NEW_ORACLE_IP:8080" \
bash scripts/register-worker.sh
```

Check health:

```bash
curl http://localhost:8080/health
curl http://localhost:8090/health
```

## Account States

`READY`, `BUSY`, `COOLDOWN`, `CAPTCHA_REQUIRED`, `TOKEN_EXPIRED`, `BROKEN_SESSION`, `BLOCKED`

## Job States

`QUEUED`, `ASSIGNED`, `PROCESSING`, `RETRYING`, `COMPLETED`, `FAILED`, `TIMEOUT`

## Configuration

Edit `config/worker.yaml` or override worker-local values with environment variables:

- `WORKER_ID`
- `REDIS_URL`
- `WORKER_CONFIG`
- `CHROME_BINARY`
- `FLOW_URL`
- `VNC_PASSWORD`
- `autostart_accounts` in YAML controls whether persisted accounts relaunch after container restart.
- `flow_settings` in YAML controls the global model, duration, estimated credits, and presets for `text_to_image`, `image_to_image`, `text_to_video`, and `image_to_video`.

Flow model selection is global by design. Accounts are execution workers only; they do not choose models.

VPS worker records are database state, not file state. The orchestrator loads
registered workers from MongoDB/PostgreSQL first. YAML/env `workers` or
`WORKER_BASE_URL` are only bootstrap seeds for first install.

## Distributed Architecture

Incoming generation requests go to the global orchestrator first. The orchestrator stores the job in Redis, reads global Flow settings, evaluates every registered VPS worker, and dispatches to the healthiest worker with capacity. The worker then queues locally and selects the best eligible account.

If the admin testing panel specifies a VPS, account, model, duration, or preset override, that override applies only to that test job and does not change production defaults.

The normal production API path does not require users to choose a VPS or account:

```bash
curl -X POST http://localhost:8090/generate/text-to-video \
  -H 'content-type: application/json' \
  -d '{"prompt":"cinematic Tokyo rain street","aspect_ratio":"9:16"}'
```

The global scheduler checks free account slots across all enabled VPS workers. If every account on every VPS is busy, the job stays in the global Redis queue and is retried until capacity opens.

## Separate Orchestrator VPS

For larger deployments, run the queue/orchestrator on its own VPS and register worker VPS nodes by URL:

```bash
docker compose -f docker-compose.orchestrator.yml up -d --build
```

Use cloud Redis by setting `ORCHESTRATOR_REDIS_URL`. Worker VPS nodes use `REDIS_URL` for their local queue namespace. Worker VPS nodes only need the worker API on `:8080`; the orchestrator can be hosted separately from browser/account machines.

## Admin Testing Panel

The distributed testing panel lives in `frontend/` and talks to the orchestrator through `/api/orchestrator`.

```bash
cd frontend
npm install
npm run dev -- --port 3001
```

Open `http://localhost:3001`.

## Persistent Data

- `chrome-profiles/`: isolated Chrome user data dirs.
- `worker/accounts/`: account YAML definitions.
- `worker/logs/`: worker logs.
- `extension/`: FlowKit extension mount. The installer can populate this from the FlowKit repository, and this checkout already uses the FlowKit extension layout.

## FlowKit Integration

The worker is designed around the existing FlowKit extension from `https://github.com/crisng95/flowkit`.

Put the unpacked FlowKit `extension/` directory at `/extension` in the container, or let `scripts/install.sh` copy it from the FlowKit repo. For each account, the worker creates a runtime copy of `/extension` and rewrites only the local bridge URLs:

- FlowKit extension WebSocket: `ws://127.0.0.1:<per-account-port>`
- FlowKit callback: `http://127.0.0.1:8080/flowkit/<account-id>/callback`

Chrome extension files, manifest shape, content scripts, injected captcha flow, request patterns, and Google Flow compatibility are otherwise preserved.

To submit a native FlowKit bridge request through the worker queue, send a job with a `flowkit` object:

```bash
curl -X POST http://localhost:8080/jobs \
  -H 'content-type: application/json' \
  -d '{
    "prompt": "FlowKit bridge request",
    "flowkit": {
      "method": "api_request",
      "params": {
        "url": "https://aisandbox-pa.googleapis.com/v1/credits?key=<google-api-key>",
        "method": "GET",
        "headers": {}
      }
    }
  }'
```

## Notes For Operations

Use VNC to manually sign in to each Google account the first time. Sessions persist in the account Chrome profile. Do not share profile directories across accounts.

The worker intentionally runs Chrome visibly in a virtual display rather than fully headless. This improves compatibility with Google Flow and makes account recovery/debugging possible.
