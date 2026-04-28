#!/bin/bash
# ============================================================================
# AstroQuant — 24/7 Start Script (tmux-based, VS Code independent)
# ============================================================================
# Starts all AstroQuant components in named tmux sessions so they keep
# running even when VS Code or the terminal is closed.
#
# Sessions created:
#   aq-redis       — Redis in-memory broker
#   aq-chrome      — Chrome with CDP for Maven bridge
#   aq-cf-unblock  — Cloudflare challenge auto-unblock (exits when done)
#   aq-backend     — FastAPI/uvicorn trading backend
#   aq-celery      — Celery async worker
#   aq-orchestrator— Signal orchestrator
#   aq-livesync    — Live data sync engine
#   aq-mt5-bridge  — MT5 CSV bridge sync daemon
#
# Usage:
#   ./start_24h.sh          # start everything
#   ./start_24h.sh --restart# stop and restart everything
#   ./start_24h.sh --status # show status of all sessions
# ============================================================================

set -euo pipefail
cd "$(dirname "$0")"

VENV="$(pwd)/.venv"
PYTHON="$VENV/bin/python3"
UVICORN="$VENV/bin/uvicorn"
CELERY="$VENV/bin/celery"
ENV_FILE="$(pwd)/.env"
LOG_DIR="$(pwd)/logs"
PROFILE_DIR="$(pwd)/data/browser_session/chrome-profile"
CDP_PORT=9222
BROKER_URL="${AQ_BROKER_URL:-https://manager.maven.markets/app/trade}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

log()  { echo -e "${GREEN}[24h]${NC} $*"; }
warn() { echo -e "${YELLOW}[24h]${NC} $*"; }
err()  { echo -e "${RED}[24h]${NC} $*" >&2; }

# ── Helpers ──────────────────────────────────────────────────────────────────

session_running() { tmux has-session -t "$1" 2>/dev/null; }

kill_session() {
  if session_running "$1"; then
    tmux kill-session -t "$1" 2>/dev/null || true
    log "Stopped: $1"
  fi
}

new_session() {
  local name="$1"; shift
  kill_session "$name" 2>/dev/null || true
  # Create detached tmux session with .env loaded
  tmux new-session -d -s "$name" -x 220 -y 50 \
    "set -a; [ -f '$ENV_FILE' ] && source '$ENV_FILE'; set +a; export PYTHONPATH=$(pwd); $*; echo '[session ended]'; exec bash"
}

wait_for_port() {
  local port="$1" max="${2:-30}"
  for _ in $(seq 1 "$max"); do
    if curl -sS --max-time 1 "http://127.0.0.1:${port}" >/dev/null 2>&1 || \
       curl -sS --max-time 1 "http://127.0.0.1:${port}/json/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_cdp() {
  local max="${1:-60}"
  for _ in $(seq 1 "$max"); do
    if curl -sS --max-time 2 "http://127.0.0.1:${CDP_PORT}/json/version" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

show_status() {
  echo ""
  echo "══════════════════════════════════════════════"
  echo "  AstroQuant 24/7 Session Status"
  echo "══════════════════════════════════════════════"
  for s in aq-redis aq-chrome aq-cf-unblock aq-backend aq-celery aq-orchestrator aq-livesync aq-mt5-bridge; do
    if session_running "$s"; then
      echo -e "  ${GREEN}●${NC} $s"
    else
      echo -e "  ${RED}○${NC} $s  (not running)"
    fi
  done
  echo ""
  # Backend health
  local health
  health=$(curl -sS --max-time 3 "http://127.0.0.1:8000/status" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('backend='+str(d.get('status','?')))" 2>/dev/null || echo "backend=unreachable")
  echo "  $health"
  local bridge
  bridge=$(curl -sS --max-time 3 "http://127.0.0.1:8000/status/broker_bridge" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('bridge='+str(d.get('status','?'))+' ready='+str(d.get('bridge_ready','?')))" 2>/dev/null || echo "bridge=unreachable")
  echo "  $bridge"
  echo ""
  echo "  Attach to a session: tmux attach -t <name>"
  echo "  Stop everything:     ./stop_24h.sh"
  echo "══════════════════════════════════════════════"
}

# ── Argument Handling ─────────────────────────────────────────────────────────
RESTART=false
STATUS_ONLY=false
for arg in "${@:-}"; do
  case "$arg" in
    --restart) RESTART=true ;;
    --status)  STATUS_ONLY=true ;;
  esac
done

if [ "$STATUS_ONLY" = true ]; then
  show_status; exit 0
fi

if [ "$RESTART" = true ]; then
  log "Stopping all sessions for clean restart..."
  for s in aq-redis aq-chrome aq-cf-unblock aq-backend aq-celery aq-orchestrator aq-livesync aq-mt5-bridge; do
    kill_session "$s"
  done
  sleep 2
fi

# ── Pre-flight checks ─────────────────────────────────────────────────────────
mkdir -p "$LOG_DIR" "$PROFILE_DIR"

if ! command -v tmux >/dev/null 2>&1; then
  err "tmux is not installed. Run: sudo apt-get install -y tmux"; exit 1
fi
if [ ! -f "$PYTHON" ]; then
  err "Virtual env not found at $VENV. Run: python3 -m venv $VENV && pip install -r requirements.txt"; exit 1
fi

# ── 1. Redis ──────────────────────────────────────────────────────────────────
if session_running "aq-redis"; then
  log "Redis already running (tmux session aq-redis)."
else
  if redis-cli ping >/dev/null 2>&1; then
    log "Redis already running (external)."
  else
    log "Starting Redis..."
    new_session "aq-redis" "redis-server --daemonize no --bind 127.0.0.1 --port 6379 --loglevel notice"
    sleep 2
    if ! redis-cli ping >/dev/null 2>&1; then
      warn "Redis did not start via tmux, trying redis-server --daemonize yes..."
      redis-server --daemonize yes --bind 127.0.0.1 --port 6379 --loglevel notice || true
      sleep 1
    fi
    redis-cli ping >/dev/null 2>&1 && log "Redis: OK" || err "Redis: FAILED"
  fi
fi

# ── 2. Chrome (headed via Xvfb) ──────────────────────────────────────────────
if session_running "aq-chrome"; then
  log "Chrome session already running (aq-chrome)."
else
  log "Starting Chrome with CDP on port $CDP_PORT..."
  # Detect or start Xvfb for headed mode (better Cloudflare compatibility)
  if ! pgrep -f "Xvfb :99" >/dev/null 2>&1; then
    if command -v Xvfb >/dev/null 2>&1; then
      nohup Xvfb :99 -screen 0 1280x900x24 -ac +extension GLX +render -noreset \
        > "$LOG_DIR/xvfb.log" 2>&1 &
      sleep 1
      log "Xvfb started on :99"
    fi
  fi
  export DISPLAY=:99

  CHROME_BIN=$(which google-chrome 2>/dev/null || which chromium-browser 2>/dev/null || which chromium 2>/dev/null || echo "")
  if [ -z "$CHROME_BIN" ]; then
    err "Chrome/Chromium not found."; exit 1
  fi

  new_session "aq-chrome" "export DISPLAY=:99; \
    '$CHROME_BIN' \
      --remote-debugging-port=$CDP_PORT \
      --remote-allow-origins=* \
      --user-data-dir='$PROFILE_DIR' \
      --no-sandbox \
      --disable-gpu \
      --disable-software-rasterizer \
      --disable-dev-shm-usage \
      --disable-blink-features=AutomationControlled \
      --disable-background-timer-throttling \
      --disable-renderer-backgrounding \
      --disable-popup-blocking \
      --disable-webgl \
      --disable-webgl2 \
      --disable-accelerated-2d-canvas \
      --disable-canvas-aa \
      --disable-gpu-compositing \
      --window-size=1280,900 \
      '$BROKER_URL' > '$LOG_DIR/chrome.log' 2>&1"

  log "Waiting for Chrome CDP to be ready..."
  if wait_for_cdp 60; then
    log "Chrome CDP ready on port $CDP_PORT."
  else
    warn "Chrome CDP not reachable after 60s — check logs/chrome.log"
  fi
fi

# ── 3. Cloudflare Auto-Unblock ────────────────────────────────────────────────
log "Running Cloudflare challenge auto-unblock..."
kill_session "aq-cf-unblock" 2>/dev/null || true
new_session "aq-cf-unblock" \
  "'$PYTHON' '$(pwd)/cloudflare_unblock.py' --cdp-wait 60 --max-wait 120 2>&1 | tee '$LOG_DIR/cf_unblock.log'"
log "CF unblock running in aq-cf-unblock (check: tmux attach -t aq-cf-unblock)"
# Give it a moment to start before launching backend
sleep 3

# ── 4. Backend (FastAPI/uvicorn) ──────────────────────────────────────────────
if session_running "aq-backend"; then
  log "Backend already running (aq-backend)."
else
  log "Starting FastAPI backend..."
  new_session "aq-backend" \
    "'$UVICORN' astroquant.backend.main:app --host 0.0.0.0 --port 8000 2>&1 | tee '$LOG_DIR/backend.log'"
  log "Waiting for backend to be ready..."
  if wait_for_port 8000 30; then
    log "Backend ready on port 8000."
  else
    warn "Backend not responding after 30s — check logs/backend.log"
  fi
fi

# ── 5. Celery Worker ──────────────────────────────────────────────────────────
if session_running "aq-celery"; then
  log "Celery already running (aq-celery)."
else
  log "Starting Celery worker..."
  new_session "aq-celery" \
    "'$CELERY' -A astroquant.backend.tasks.celery_worker worker --loglevel=info 2>&1 | tee '$LOG_DIR/celery.log'"
  sleep 3
  log "Celery started."
fi

# ── 6. Orchestrator ───────────────────────────────────────────────────────────
if session_running "aq-orchestrator"; then
  log "Orchestrator already running (aq-orchestrator)."
else
  log "Starting signal orchestrator..."
  new_session "aq-orchestrator" \
    "'$PYTHON' '$(pwd)/start_astroquant.py' 2>&1 | tee '$LOG_DIR/orchestrator.log'"
  sleep 3
  log "Orchestrator started."
fi

# ── 7. Live Sync ──────────────────────────────────────────────────────────────
if session_running "aq-livesync"; then
  log "LiveSync already running (aq-livesync)."
else
  if [ -f "$(pwd)/start_live_sync.py" ]; then
    log "Starting live sync engine..."
    new_session "aq-livesync" \
      "'$PYTHON' '$(pwd)/start_live_sync.py' 2>&1 | tee '$LOG_DIR/livesync.log'"
    sleep 2
    log "LiveSync started."
  else
    log "start_live_sync.py not found — skipping livesync."
  fi
fi

# ── 8. MT5 Bridge Sync (MetaEditor CSV -> canonical TF datasets) ────────────
if session_running "aq-mt5-bridge"; then
  log "MT5 bridge sync already running (aq-mt5-bridge)."
else
  if [ -f "$(pwd)/tools/mt5_bridge_sync_daemon.py" ]; then
    log "Starting MT5 bridge sync daemon..."
    new_session "aq-mt5-bridge" \
      "export MT5_BRIDGE_SOURCE_DIR='$(pwd)/market-causality-lab/data/live/mt5/incoming'; export MT5_BRIDGE_OUT_DIR='$(pwd)/market-causality-lab/data/live/mt5'; export MT5_BRIDGE_DATA_DIR='$(pwd)/market-causality-lab/data'; export MT5_BRIDGE_TIMEFRAME='5m'; export MT5_BRIDGE_PERSIST_HISTORY='1'; '${PYTHON}' '$(pwd)/tools/mt5_bridge_sync_daemon.py' 2>&1 | tee '$LOG_DIR/mt5_bridge_sync.log'"
    sleep 2
    log "MT5 bridge sync started."
  else
    log "tools/mt5_bridge_sync_daemon.py not found — skipping MT5 bridge sync."
  fi
fi

# ── Final Status ──────────────────────────────────────────────────────────────
sleep 2
show_status

echo ""
log "Full 24/7 stack is running. Sessions persist without VS Code."
log "Monitor logs in: $LOG_DIR/"
log "Stop everything: ./stop_24h.sh"
log "Re-attach to any session: tmux attach -t <session-name>"
