#!/usr/bin/env bash
# scripts/run_server.sh — launch the MetaboAgent FastAPI backend.
#
# Loads .env, sets HF_HOME to the repo's configured model cache, then exec's
# uvicorn. Honors APP_HOST (default 127.0.0.1) and APP_PORT (default 8080).
#
# Usage:
#   bash scripts/run_server.sh            # 127.0.0.1:8080
#   APP_PORT=9000 bash scripts/run_server.sh
#   APP_HOST=0.0.0.0 bash scripts/run_server.sh   # LAN-exposed; opt-in only

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found at $REPO_ROOT/.env" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

export HF_HOME="${HF_HOME:-/mnt/storage_sdd/huggingface}"
export PYTHONPATH="$REPO_ROOT"

APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8080}"

echo "[run_server] APP_HOST=${APP_HOST} APP_PORT=${APP_PORT}"
echo "[run_server] PRIMARY_LLM_BASE_URL=${PRIMARY_LLM_BASE_URL:-unset}"
echo "[run_server] HF_HOME=${HF_HOME}"

exec uvicorn app.server:app --host "${APP_HOST}" --port "${APP_PORT}" --log-level info
