#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/flow-worker}"
BRANCH="${BRANCH:-main}"

if [[ "${EUID}" -ne 0 ]]; then
  SUDO="sudo -E"
else
  SUDO=""
fi

if [[ ! -d "${APP_DIR}/.git" ]]; then
  echo "${APP_DIR} is not a Git checkout. Install first with REPO_URL set." >&2
  exit 1
fi

cd "${APP_DIR}"
git fetch origin "${BRANCH}"
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

${SUDO} docker compose build
${SUDO} docker compose up -d

bash "${APP_DIR}/scripts/register-worker.sh" || true

echo "Flow Worker Appliance updated."
echo "Health: http://$(hostname -I | awk '{print $1}'):8080/health"
