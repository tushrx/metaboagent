#!/usr/bin/env bash
# scripts/stop_demo.sh — failsafe cleanup for run_demo.sh.
#
# If run_demo.sh's trap was bypassed (terminal closed, SIGKILL, crash) and
# leftover backend (8080) or UI (3100) processes are still listening, this
# script finds them by port and tears them down. Pure SIGTERM with a 5s
# fallback to SIGKILL.
#
# No-op when nothing is listening — clean exit, prints "no processes to stop".

set -euo pipefail

PORTS=(8080 3100)

find_pids() {
  local port="$1"
  # ss is part of iproute2 and present on every modern Linux box. lsof would
  # work too but isn't always installed.
  ss -tlnpH "sport = :$port" 2>/dev/null \
    | grep -oE 'pid=[0-9]+' \
    | cut -d= -f2 \
    | sort -u
}

ALL_PIDS=()
for port in "${PORTS[@]}"; do
  while IFS= read -r pid; do
    [[ -n "$pid" ]] && ALL_PIDS+=("$pid")
  done < <(find_pids "$port")
done

if [[ ${#ALL_PIDS[@]} -eq 0 ]]; then
  echo "[stop_demo] no processes to stop on ports ${PORTS[*]}."
  exit 0
fi

# De-dup (a process could own both ports, unlikely but cheap).
mapfile -t UNIQ_PIDS < <(printf '%s\n' "${ALL_PIDS[@]}" | sort -u)

echo "[stop_demo] sending SIGTERM to PIDs: ${UNIQ_PIDS[*]}"
for pid in "${UNIQ_PIDS[@]}"; do
  kill -TERM "$pid" 2>/dev/null || true
done

# Wait up to 5s for graceful exit.
for _ in 1 2 3 4 5; do
  any_alive=0
  for pid in "${UNIQ_PIDS[@]}"; do
    if kill -0 "$pid" 2>/dev/null; then any_alive=1; break; fi
  done
  if [[ "$any_alive" -eq 0 ]]; then
    echo "[stop_demo] all processes exited cleanly."
    exit 0
  fi
  sleep 1
done

echo "[stop_demo] some processes survived SIGTERM; sending SIGKILL."
for pid in "${UNIQ_PIDS[@]}"; do
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null || true
  fi
done
echo "[stop_demo] done."
