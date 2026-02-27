#!/usr/bin/env bash
set -euo pipefail

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5500}"

kill_pattern() {
  local pattern="$1"
  if pgrep -f "${pattern}" >/dev/null 2>&1; then
    echo "[stop] killing processes matching: ${pattern}"
    pkill -f "${pattern}" || true
  fi
}

kill_port_listener() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"${port}" || true)"
  if [[ -n "${pids}" ]]; then
    echo "[stop] killing listeners on :${port} -> ${pids}"
    kill -9 ${pids} || true
  fi
}

echo "[stop] stopping backend/frontend services"
kill_pattern "uvicorn backend.main:app"
kill_pattern "python3 -m http.server ${FRONTEND_PORT}"
kill_port_listener "${BACKEND_PORT}"
kill_port_listener "${FRONTEND_PORT}"

echo "[stop] done"
