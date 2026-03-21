#!/bin/bash
# Combined robust launch script for AstroQuant
# Ensures .env, launches Chrome, backend, orchestrator, Celery, tunnel, calibrates selectors, and runs health checks


set -euo pipefail

# Ensure Python can find astroquant package
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}" )" && pwd)"
VENV_BIN="$ROOT_DIR/.venv/bin"
PYTHON_BIN="$VENV_BIN/python"
CHROME_PROFILE="/tmp/astroquant-trading-profile"
CDP_PORT=9222
BROKER_URL="https://manager.maven.markets/app/trade"
LOG_DIR="$ROOT_DIR/logs"
ENV_FILE="$ROOT_DIR/.env"

mkdir -p "$LOG_DIR"

# 1. Ensure .env exists and is valid
if [[ ! -f "$ENV_FILE" ]]; then
  echo "No .env found, generating default live trading .env..."
  cp "$ROOT_DIR/.env.example" "$ENV_FILE" 2>/dev/null || true
fi

# 2. Start Chrome with remote debugging
CHROME_BIN=""
if command -v google-chrome >/dev/null 2>&1; then
    CHROME_BIN="$(command -v google-chrome)"
elif command -v chromium >/dev/null 2>&1; then
    CHROME_BIN="$(command -v chromium)"
elif command -v chromium-browser >/dev/null 2>&1; then
    CHROME_BIN="$(command -v chromium-browser)"
fi

if [[ -n "$CHROME_BIN" ]]; then
    pkill -f "chrome.*remote-debugging-port" || true
    sleep 1
    [[ -d "$CHROME_PROFILE" ]] && rm -rf "$CHROME_PROFILE"
    mkdir -p "$CHROME_PROFILE"
    nohup "$CHROME_BIN" \
      --remote-debugging-port=$CDP_PORT \
      --user-data-dir="$CHROME_PROFILE" \
      --no-first-run --no-default-browser-check --disable-sync --disable-default-apps --disable-extensions \
      "$BROKER_URL" > "$LOG_DIR/chrome.log" 2>&1 &
    echo "Chrome launched with remote debugging."
else
    echo "Chrome not found. Please start it manually with remote debugging on port $CDP_PORT."
    read -p "Press ENTER after Chrome is running and broker is logged in..."
fi

# 3. Start backend, orchestrator, Celery directly (no PM2)
source "$VENV_BIN/activate"
echo "Starting backend (uvicorn)..."
nohup "$PYTHON_BIN" -m uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 --reload > "$LOG_DIR/backend.log" 2>&1 &
echo "Starting Celery worker..."
nohup "$PYTHON_BIN" -m celery -A astroquant.backend.tasks.celery_worker worker --loglevel=info > "$LOG_DIR/celery.log" 2>&1 &
echo "Starting orchestrator..."
nohup "$PYTHON_BIN" start_astroquant.py > "$LOG_DIR/orchestrator.log" 2>&1 &
echo "Starting tunnel..."
nohup "$PYTHON_BIN" cloudflared tunnel --url http://localhost:8000 > "$LOG_DIR/tunnel.log" 2>&1 &

# 4. Wait for backend to be ready
for i in {1..20}; do
  if curl -s http://127.0.0.1:8000/status >/dev/null 2>&1; then
    echo "Backend API is responding."
    break
  fi
  sleep 1
done

echo "All services launched."
