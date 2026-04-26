#!/usr/bin/env bash
# scripts/run_demo.sh — single-command demo launch (Phase 7.4).
#
# Boots MetaboAgent in fully offline-safe demo mode: warmed cache + indexed
# corpus only, no live HTTP. Starts the FastAPI backend on 127.0.0.1:8080
# and the Next.js UI on 127.0.0.1:3100. Pure orchestration — installs
# nothing, builds nothing.
#
# Refuses to run unless:
#   - data/demo_cache/  has been populated by scripts/warm_demo_cache.py
#   - the vLLM E4B service is reachable at $PRIMARY_LLM_BASE_URL
#   - ui/web/node_modules/ exists (npm install was run)
#
# Ctrl+C cleanly stops both child processes. If the trap is bypassed
# (e.g. terminal closed), use scripts/stop_demo.sh to clean up by port.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ---- 1. Load .env ---------------------------------------------------------
if [[ ! -f .env ]]; then
  echo "ERROR: .env not found at $REPO_ROOT/.env" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${PRIMARY_LLM_API_KEY:?PRIMARY_LLM_API_KEY must be set in .env}"
: "${VLLM_API_KEY:?VLLM_API_KEY must be set in .env}"

# ---- 2. Demo / offline flags ---------------------------------------------
export DEMO_MODE=1
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export HF_HOME="${HF_HOME:-/mnt/storage_sdd/huggingface}"
export PYTHONPATH="$REPO_ROOT"

PRIMARY_LLM_BASE_URL="${PRIMARY_LLM_BASE_URL:-http://127.0.0.1:8001/v1}"
APP_HOST="127.0.0.1"
APP_PORT="8080"
UI_HOST="127.0.0.1"
UI_PORT="3100"

# ---- 3. Preflight checks --------------------------------------------------
if [[ ! -d "$REPO_ROOT/data/demo_cache" ]] \
   || [[ -z "$(ls -A "$REPO_ROOT/data/demo_cache" 2>/dev/null)" ]]; then
  echo "ERROR: data/demo_cache/ is missing or empty." >&2
  echo "       Run scripts/warm_demo_cache.py first against a non-DEMO backend." >&2
  exit 1
fi
CACHE_QUERIES=$(find "$REPO_ROOT/data/demo_cache" -mindepth 1 -maxdepth 1 -type d | wc -l)
CACHE_CALLS=$(find "$REPO_ROOT/data/demo_cache" -name tool_calls.json \
               -exec python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' {} \; \
               | awk '{s+=$1} END {print s+0}')

if ! curl -sf -m 5 "$PRIMARY_LLM_BASE_URL/models" >/dev/null 2>&1; then
  echo "ERROR: vLLM E4B service must be running on $PRIMARY_LLM_BASE_URL." >&2
  echo "       Check: sudo systemctl status vllm-e4b   (or scripts/serve_e4b.sh)" >&2
  exit 1
fi

if [[ ! -d "$REPO_ROOT/ui/web/node_modules" ]]; then
  echo "ERROR: ui/web/node_modules not found. Run 'npm install' in ui/web/ first." >&2
  exit 1
fi

mkdir -p "$REPO_ROOT/logs"
BACKEND_LOG="$REPO_ROOT/logs/demo_backend.log"
UI_LOG="$REPO_ROOT/logs/demo_ui.log"

# ---- 4. Cleanup trap ------------------------------------------------------
BACKEND_PID=""
UI_PID=""

# Each child runs under setsid so its PID is also a PGID — the trap can
# then signal the whole group, catching node/uvicorn descendants.
kill_group() {
  local pid="$1"
  [[ -z "$pid" ]] && return 0
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -"$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  fi
}
hard_kill_group() {
  local pid="$1"
  [[ -z "$pid" ]] && return 0
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -"$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
}

cleanup() {
  local rc=$?
  trap - INT TERM EXIT
  echo
  echo "[run_demo] shutting down…"
  kill_group "$UI_PID"
  kill_group "$BACKEND_PID"
  for _ in 1 2 3 4 5; do
    if [[ -n "$UI_PID" ]] && kill -0 "$UI_PID" 2>/dev/null; then sleep 1; continue; fi
    if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then sleep 1; continue; fi
    break
  done
  hard_kill_group "$UI_PID"
  hard_kill_group "$BACKEND_PID"
  exit "$rc"
}
trap cleanup INT TERM EXIT

# ---- 5. Start backend -----------------------------------------------------
echo "[run_demo] starting FastAPI backend on http://${APP_HOST}:${APP_PORT}"
setsid bash -c "cd '$REPO_ROOT' && exec uvicorn app.server:app --host '$APP_HOST' --port '$APP_PORT' --log-level info" \
  >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Poll /health until demo_mode: true (or fail fast).
for i in $(seq 1 15); do
  if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "ERROR: backend exited during startup. Tail of $BACKEND_LOG:" >&2
    tail -n 30 "$BACKEND_LOG" >&2 || true
    exit 1
  fi
  HEALTH=$(curl -sf -m 2 "http://${APP_HOST}:${APP_PORT}/health" 2>/dev/null || true)
  if [[ -n "$HEALTH" ]] && \
     printf '%s' "$HEALTH" | python3 -c '
import json, sys
d = json.load(sys.stdin)
sys.exit(0 if d.get("demo_mode") is True else 1)
' 2>/dev/null; then
    echo "[run_demo] backend healthy (demo_mode=true) after ${i}s"
    break
  fi
  if [[ "$i" -eq 15 ]]; then
    echo "ERROR: backend /health did not report demo_mode=true within 15s." >&2
    echo "       Tail of $BACKEND_LOG:" >&2
    tail -n 30 "$BACKEND_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done

# ---- 6. Start UI ----------------------------------------------------------
echo "[run_demo] starting Next.js UI on http://${UI_HOST}:${UI_PORT}"
setsid bash -c "cd '$REPO_ROOT/ui/web' && exec npm run dev -- -p '$UI_PORT' -H '$UI_HOST'" \
  >"$UI_LOG" 2>&1 &
UI_PID=$!

for i in $(seq 1 30); do
  if ! kill -0 "$UI_PID" 2>/dev/null; then
    echo "ERROR: UI exited during startup. Tail of $UI_LOG:" >&2
    tail -n 30 "$UI_LOG" >&2 || true
    exit 1
  fi
  if curl -sf -m 2 "http://${UI_HOST}:${UI_PORT}/" >/dev/null 2>&1; then
    echo "[run_demo] UI ready after ${i}s"
    break
  fi
  if [[ "$i" -eq 30 ]]; then
    echo "ERROR: UI did not become reachable within 30s." >&2
    echo "       Tail of $UI_LOG:" >&2
    tail -n 30 "$UI_LOG" >&2 || true
    exit 1
  fi
  sleep 1
done

# ---- 7. Banner ------------------------------------------------------------
cat <<EOF

═══════════════════════════════════════════════════════════════
  MetaboAgent — Demo Mode
═══════════════════════════════════════════════════════════════
  Backend:    http://${APP_HOST}:${APP_PORT}
  UI:         http://${UI_HOST}:${UI_PORT}
  Health:     curl http://${APP_HOST}:${APP_PORT}/health
  Cache:      data/demo_cache/ (${CACHE_QUERIES} queries, ${CACHE_CALLS} tool calls)
  Logs:       ${BACKEND_LOG}
              ${UI_LOG}
═══════════════════════════════════════════════════════════════
  Press Ctrl+C to stop both services.

EOF

# ---- 8. Wait on children --------------------------------------------------
# `wait -n` returns when any child exits; treat that as a fatal condition
# and let the trap clean the survivor up.
wait -n "$BACKEND_PID" "$UI_PID" || true
echo "[run_demo] one of the child processes exited; tearing down."
