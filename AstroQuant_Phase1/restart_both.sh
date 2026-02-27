#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5500}"
BACKEND_LOG="${BACKEND_LOG:-/tmp/aq_backend.log}"
FRONTEND_LOG="${FRONTEND_LOG:-/tmp/aq_frontend.log}"

kill_port_listener() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"${port}" || true)"
  if [[ -n "${pids}" ]]; then
    echo "[restart] killing listeners on :${port} -> ${pids}"
    kill -9 ${pids} || true
  fi
}

wait_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-12}"
  local sleep_sec="${4:-1}"

  for ((i=1; i<=attempts; i++)); do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      echo "[restart] ${label} is up: ${url}"
      return 0
    fi
    sleep "${sleep_sec}"
  done

  echo "[restart] ${label} failed health check: ${url}"
  return 1
}

echo "[restart] stopping stale services"
pkill -f "uvicorn backend.main:app" >/dev/null 2>&1 || true
pkill -f "python3 -m http.server ${FRONTEND_PORT}" >/dev/null 2>&1 || true
kill_port_listener "${BACKEND_PORT}"
kill_port_listener "${FRONTEND_PORT}"
sleep 1

echo "[restart] starting backend on :${BACKEND_PORT}"
(
  cd "${ROOT_DIR}"
  nohup python3 -m uvicorn backend.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" >"${BACKEND_LOG}" 2>&1 &
)

echo "[restart] starting frontend on :${FRONTEND_PORT}"
(
  cd "${ROOT_DIR}/frontend"
  nohup python3 -m http.server "${FRONTEND_PORT}" >"${FRONTEND_LOG}" 2>&1 &
)

wait_http "http://127.0.0.1:${BACKEND_PORT}/status" "backend"
wait_http "http://127.0.0.1:${FRONTEND_PORT}/" "frontend"

echo "[restart] done"
echo "[restart] backend log: ${BACKEND_LOG}"
echo "[restart] frontend log: ${FRONTEND_LOG}"
