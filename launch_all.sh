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
UNATTENDED_PREFLIGHT_SCRIPT="$ROOT_DIR/preflight_unattended.sh"
DISABLE_BROKER_AUTO_OPEN="${AQ_DISABLE_BROKER_AUTO_OPEN:-true}"

mkdir -p "$LOG_DIR"

# Stop any legacy/old-project processes before launching the current stack.
pkill -f "AstroQuant_Phase1|restart_both.sh|stop_both.sh" 2>/dev/null || true

# 1. Ensure .env exists and is valid
if [[ ! -f "$ENV_FILE" ]]; then
  echo "No .env found, generating default live trading .env..."
  cp "$ROOT_DIR/.env.example" "$ENV_FILE" 2>/dev/null || true
fi

# 2. Start Chrome with remote debugging (container-safe)
if [[ "$DISABLE_BROKER_AUTO_OPEN" == "true" ]]; then
  echo "Broker auto-open is disabled (AQ_DISABLE_BROKER_AUTO_OPEN=true)."
  echo "Use start_chrome_remote_debug.sh manually when broker automation is needed."
elif [[ -x "$ROOT_DIR/start_chrome_remote_debug.sh" ]]; then
  AQ_CHROME_MODE="${AQ_CHROME_MODE:-headed}" nohup bash "$ROOT_DIR/start_chrome_remote_debug.sh" > "$LOG_DIR/chrome.log" 2>&1 &
  echo "Chrome remote debug launcher started."
else
  echo "Missing start_chrome_remote_debug.sh. Please start Chrome manually on port $CDP_PORT."
fi

# 3. Start backend, orchestrator, Celery directly (no PM2)
source "$VENV_BIN/activate"
echo "Starting backend (uvicorn)..."
nohup "$PYTHON_BIN" -m uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 > "$LOG_DIR/backend.log" 2>&1 &
if "$PYTHON_BIN" -m pip show celery >/dev/null 2>&1; then
  echo "Starting Celery worker..."
  nohup "$PYTHON_BIN" -m celery -A astroquant.backend.tasks.celery_worker worker --loglevel=info > "$LOG_DIR/celery.log" 2>&1 &
else
  echo "Celery not installed in .venv, skipping worker startup."
fi
echo "Starting orchestrator..."
nohup "$PYTHON_BIN" start_astroquant.py > "$LOG_DIR/orchestrator.log" 2>&1 &
if command -v cloudflared >/dev/null 2>&1; then
  echo "Starting tunnel..."
  nohup cloudflared tunnel --url http://localhost:8000 > "$LOG_DIR/tunnel.log" 2>&1 &
else
  echo "cloudflared binary not found, skipping tunnel startup."
fi

# 4. Wait for backend to be ready
backend_ready=0
for i in {1..40}; do
  if curl -sS --max-time 2 http://127.0.0.1:8000/health >/dev/null 2>&1 || \
     curl -sS --max-time 2 http://127.0.0.1:8000/status >/dev/null 2>&1; then
    backend_ready=1
    echo "Backend API is responding."
    break
  fi
  sleep 1
done

if [[ "$backend_ready" -ne 1 ]]; then
  echo "Backend did not become ready in time. Check $LOG_DIR/backend.log"
  exit 1
fi

# 5. Block unattended automation unless the full bridge is ready
if [[ -f "$UNATTENDED_PREFLIGHT_SCRIPT" ]]; then
  chmod +x "$UNATTENDED_PREFLIGHT_SCRIPT" 2>/dev/null || true
  echo "Running unattended preflight gate..."
  if ! bash "$UNATTENDED_PREFLIGHT_SCRIPT" "http://127.0.0.1:8000"; then
    echo "Unattended preflight failed. Leaving services running for inspection, but launch_all.sh is blocking automation success."
    exit 1
  fi
fi

# 6. Auto-attach Playwright to Maven tab so basis/offset calculations begin immediately
if [[ "$DISABLE_BROKER_AUTO_OPEN" != "true" ]]; then
  echo "Attaching Playwright to Maven broker tab (broker_bridge/recover)..."
  _rr=$(curl -s --max-time 25 -X POST "http://127.0.0.1:8000/status/broker_bridge/recover?force_reconnect=true" 2>/dev/null || echo "")
  _br=$(echo "$_rr" | "$PYTHON_BIN" -c "
import json,sys
try:
  d=json.load(sys.stdin)
  print('yes' if d.get('bridge',{}).get('bridge_ready') else 'no')
except:
  print('no')
" 2>/dev/null || echo "no")
  if [[ "$_br" == "yes" ]]; then
    echo "✓ Maven broker bridge ready — XAUUSD quote + offset calculation live"
  else
    echo "⚠ Broker bridge not fully ready. If Maven requires login/Cloudflare challenge, complete it in the browser tab, then run:"
    echo "  curl -X POST http://127.0.0.1:8000/status/broker_bridge/recover"
  fi
fi

echo "All services launched."
