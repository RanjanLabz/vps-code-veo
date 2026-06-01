#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/flow-worker}"
ENV_FILE="${ENV_FILE:-${APP_DIR}/.env}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

ORCHESTRATOR_URL="${ORCHESTRATOR_URL:-${ORCHESTRATOR_PUBLIC_URL:-}}"
ORCHESTRATOR_API_KEY="${ORCHESTRATOR_API_KEY:-}"
WORKER_ID="${WORKER_ID:-vps-1}"
WORKER_MAX_JOBS="${WORKER_MAX_JOBS:-10}"
WORKER_WEIGHT="${WORKER_WEIGHT:-100}"

if [[ -z "${ORCHESTRATOR_URL}" || -z "${ORCHESTRATOR_API_KEY}" ]]; then
  echo "Skipping worker registration: ORCHESTRATOR_URL and ORCHESTRATOR_API_KEY are required."
  exit 0
fi

if [[ -n "${WORKER_PUBLIC_URL:-}" ]]; then
  BASE_URL="${WORKER_PUBLIC_URL}"
else
  PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org || hostname -I | awk '{print $1}')"
  BASE_URL="http://${PUBLIC_IP}:8080"
fi

payload="$(
  python3 - <<PY
import json
print(json.dumps({
    "id": "${WORKER_ID}",
    "base_url": "${BASE_URL}",
    "enabled": True,
    "max_jobs": int("${WORKER_MAX_JOBS}"),
    "weight": int("${WORKER_WEIGHT}"),
}))
PY
)"

curl -fsS \
  -X POST "${ORCHESTRATOR_URL%/}/workers" \
  -H "content-type: application/json" \
  -H "x-api-key: ${ORCHESTRATOR_API_KEY}" \
  -d "${payload}"

echo
echo "Registered worker ${WORKER_ID} at ${BASE_URL}"
