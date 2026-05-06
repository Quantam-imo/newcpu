#!/bin/bash
# AstroQuant 24/7 Full Stack Auto-Start (Container-Compatible)
# Starts all services in correct order with monitoring and auto-restart
# Usage: ./start_24h_fullstack.sh [--no-chrome] [--no-tunnel] [--no-novpn]

# Do NOT use set -e here — individual service failures must not abort the
# whole script; Chrome/tunnels/Telegram must always start even if backend
# is slow on cold boot. The health loop handles recovery.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"

source ~/.bashrc 2>/dev/null || true
source "$WORKSPACE/.venv/bin/activate" 2>/dev/null || true
[ -f "$WORKSPACE/.env" ] && set -a && . "$WORKSPACE/.env" && set +a

# Configuration
DATA_DIR="$WORKSPACE/data"
LOG_DIR="$DATA_DIR/logs"
LOCK_FILE="/tmp/astroquant_fullstack.lock"
LIVESYNC_DISABLE_MARKER="$LOG_DIR/livesync.disabled"
HEALTHCHECK_INTERVAL=30
STARTUP_TIMEOUT=60
NO_CHROME=false
NO_TUNNEL=false
NO_NOVPN=false
# AQ_ENABLE_VNC=false in .env disables VNC/noVPN stack (required for WSL2/headless)
[ "${AQ_ENABLE_VNC:-true}" = "false" ] && NO_NOVPN=true

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --no-chrome)
      NO_CHROME=true
      shift
      ;;
    --no-tunnel)
      NO_TUNNEL=true
      shift
      ;;
    --no-novpn)
      NO_NOVPN=true
      shift
      ;;
    *)
      shift
      ;;
  esac
done

# Create directories
mkdir -p "$LOG_DIR" "$DATA_DIR"

# Singleton guard: never allow parallel fullstack launch loops.
if [ -f "$LOCK_FILE" ]; then
  _old_pid="$(cat "$LOCK_FILE" 2>/dev/null || true)"
  if [ -n "$_old_pid" ] && kill -0 "$_old_pid" 2>/dev/null; then
    echo "Fullstack already running (PID: $_old_pid). Exiting duplicate launcher." | tee -a "$LOG_DIR/fullstack.log"
    exit 0
  fi
  rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
trap 'if [ -f "$LOCK_FILE" ] && [ "$(cat "$LOCK_FILE" 2>/dev/null)" = "$$" ]; then rm -f "$LOCK_FILE"; fi' EXIT

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging function
log() {
  local level=$1
  shift
  local msg="$@"
  local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  echo -e "${!level}[$timestamp] $msg${NC}" | tee -a "$LOG_DIR/fullstack.log"
}

# Startup banner
echo ""
echo "========================================="
echo "  AstroQuant 24/7 Full Stack Startup"
echo "========================================="
echo "Time: $(date)"
echo "Runtime: $(ps -p 1 -o comm= 2>/dev/null || echo unknown)"
[ "$NO_CHROME" = true ] && echo "Chrome: DISABLED"
[ "$NO_TUNNEL" = true ] && echo "Tunnel: DISABLED"
[ "$NO_NOVPN" = true ] && echo "NoVPN: DISABLED"
echo "========================================="
echo ""

# Step 1: Redis
log BLUE "Starting Redis server..."
# On physical CPU with 32GB RAM: allow up to 4GB for Redis cache with LRU eviction.
# In codespace/container: use 512mb safe default.
_AQ_REDIS_MAXMEM="${AQ_REDIS_MAXMEM:-1gb}"
redis-server --daemonize yes \
  --logfile "$LOG_DIR/redis.log" \
  --maxmemory "$_AQ_REDIS_MAXMEM" \
  --maxmemory-policy allkeys-lru \
  --save "" \
  --appendonly no \
  2>/dev/null || true
# Retry up to 10 seconds — Redis is fast but daemonize can be slightly delayed
_redis_ok=false
for _r in 1 2 3 4 5; do
  sleep 2
  if redis-cli ping > /dev/null 2>&1; then
    _redis_ok=true
    break
  fi
done

if [ "$_redis_ok" = true ]; then
  log GREEN "✓ Redis running on port 6379"
else
  # Redis is fundamental — try service fallback, then hard fail
  service redis-server start 2>/dev/null || true
  sleep 2
  if redis-cli ping > /dev/null 2>&1; then
    log GREEN "✓ Redis running (via service command)"
  else
    log RED "✗ Redis failed to start — cannot continue"
    exit 1
  fi
fi

# Step 2: Celery
log BLUE "Starting Celery worker..."
cd "$WORKSPACE"
# Enforce singleton worker across repeated boots/recovery runs.
pkill -f "celery.*astroquant.backend.tasks.celery_worker" 2>/dev/null || true
sleep 1
# Auto-scale: env override, or 2× CPU cores capped at 8 for trading safety.
_AQ_CELERY_CONCUR="${CELERY_CONCURRENCY:-$(python3 -c "import os; print(min(8, max(4, (os.cpu_count() or 4) * 2)))" 2>/dev/null || echo 4)}"
nohup celery -A astroquant.backend.tasks.celery_worker:celery_app worker \
  --loglevel=info \
  --logfile="$LOG_DIR/celery.log" \
  --pidfile="$LOG_DIR/celery.pid" \
  --pool=threads \
  --concurrency="$_AQ_CELERY_CONCUR" \
  > "$LOG_DIR/celery.log" 2>&1 &

sleep 3
if pgrep -f "celery.*worker" > /dev/null; then
  log GREEN "✓ Celery worker running"
else
  log YELLOW "⚠ Celery worker not yet detected — continuing (health loop will restart it)"
fi

# Step 3: Orchestrator
log BLUE "Starting multi-symbol orchestrator..."
# Enforce singleton orchestrator across repeated boots/recovery runs.
pkill -f "python .*start_astroquant.py|/start_astroquant.py" 2>/dev/null || true
sleep 1
nohup python "$WORKSPACE/start_astroquant.py" > "$LOG_DIR/orchestrator.log" 2>&1 &
ORCH_PID=$!
echo $ORCH_PID > "$LOG_DIR/orchestrator.pid"
sleep 4

if kill -0 $ORCH_PID 2>/dev/null; then
  log GREEN "✓ Orchestrator running (PID: $ORCH_PID)"
else
  log YELLOW "⚠ Orchestrator not yet detected — continuing (health loop will restart it)"
fi

# Step 4: FastAPI Backend
log BLUE "Starting FastAPI backend (uvicorn)..."
cd "$WORKSPACE"
# Enforce singleton backend across repeated boots/recovery runs.
pkill -f "uvicorn.*astroquant.backend.main:app" 2>/dev/null || true
sleep 1
# Prefer a single worker for long-lived websocket/polling stability.
# Override with FASTAPI_WORKERS only if you explicitly need multi-worker mode.
_AQ_WORKERS="${FASTAPI_WORKERS:-1}"
_AQ_LOG_LEVEL="${FASTAPI_LOG_LEVEL:-warning}"

# Chart engine tuning for real-time trading responsiveness.
export MCL_CHART_PROCESS_POOL_ENABLED="${MCL_CHART_PROCESS_POOL_ENABLED:-1}"
export MCL_CHART_PROCESS_POOL_MAX_WORKERS="${MCL_CHART_PROCESS_POOL_MAX_WORKERS:-2}"
export MCL_CHART_PROCESS_POOL_TIMEOUT_SECONDS="${MCL_CHART_PROCESS_POOL_TIMEOUT_SECONDS:-40}"
export MCL_CHART_PROCESS_POOL_START_METHOD="${MCL_CHART_PROCESS_POOL_START_METHOD:-spawn}"
export MCL_CHART_PREWARM_ENABLED="${MCL_CHART_PREWARM_ENABLED:-1}"
export MCL_CHART_PREWARM_DELAY_SECONDS="${MCL_CHART_PREWARM_DELAY_SECONDS:-3}"
export MCL_CHART_PREWARM_SPECS="${MCL_CHART_PREWARM_SPECS:-XAUUSD:5m:realtime:1800:1,XAUUSD:15m:balanced:2200:2,XAUUSD:1h:balanced:3200:3,XAUUSD:4h:balanced:4200:5,XAUUSD:1d:deep:12000:15}"

nohup python -m uvicorn astroquant.backend.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers "$_AQ_WORKERS" \
  --log-level "$_AQ_LOG_LEVEL" \
  > "$LOG_DIR/backend.log" 2>&1 &
echo $! > "$LOG_DIR/backend.pid"
log GREEN "✓ Backend starting with $_AQ_WORKERS workers"

# Retry up to 45 seconds — cold boot takes longer than 6s
_backend_ok=false
for _i in 1 2 3 4 5 6 7 8 9; do
  sleep 5
  if curl -fsS http://127.0.0.1:8000/health > /dev/null 2>&1 \
     || curl -fsS http://127.0.0.1:8000/status/feed > /dev/null 2>&1; then
    _backend_ok=true
    break
  fi
  log YELLOW "⏳ Waiting for backend... (attempt $_i/9)"
done

if [ "$_backend_ok" = true ]; then
  log GREEN "✓ FastAPI backend running on port 8000"
else
  log YELLOW "⚠ Backend not yet responding after 45s — Chrome/tunnels/Telegram will still start; health loop monitors recovery"
fi

# Step 5: Chrome Remote Debug (optional)
if [ "$NO_CHROME" != true ]; then
  log BLUE "Starting Chrome for broker bridge..."
  pkill -f "start_chrome_remote_debug.sh" 2>/dev/null || true
  pkill -f "chrome.*remote-debugging-port=9222" 2>/dev/null || true

  # Use display from env (defaults to :99 for Xvfb / virtual); on physical CPU
  # with a real desktop DISPLAY=:0 is already set and start_chrome_remote_debug.sh
  # will detect it and skip Xvfb automatically.
  _CHROME_DISPLAY="${DISPLAY:-${AQ_XVFB_DISPLAY:-:99}}"

  _CHROME_DISPLAY="$_CHROME_DISPLAY" \
  AQ_WORKSPACE="$WORKSPACE" \
  AQ_API_BASE="http://127.0.0.1:8000" \
  AQ_CHROME_PROFILE_DIR="$DATA_DIR/browser_session/chrome-profile" \
  AQ_XVFB_DISPLAY="${AQ_XVFB_DISPLAY:-:99}" \
  AQ_USE_XVFB="${AQ_USE_XVFB:-true}" \
  nohup bash "$WORKSPACE/start_chrome_remote_debug.sh" > "$LOG_DIR/chrome.log" 2>&1 &

  # Wait for Chrome CDP to become reachable
  _cdp_ready=false
  for _i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15; do
    if curl -s --max-time 2 http://127.0.0.1:9222/json/version > /dev/null 2>&1; then
      _cdp_ready=true; break
    fi
    sleep 1
  done

  if [ "$_cdp_ready" = true ]; then
    log GREEN "✓ Chrome CDP listening on port 9222"
    # Attach Playwright to Maven tab and calibrate selectors automatically.
    # On physical CPU this ensures the broker bridge is ready without manual steps.
    log BLUE "Attaching Playwright to Maven broker tab..."
    sleep 3
    _recover_resp=$(curl -s --max-time 30 -X POST \
      "http://127.0.0.1:8000/status/broker_bridge/recover?force_reconnect=true" 2>/dev/null || echo "")
    _bridge_ready=$(echo "$_recover_resp" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print('yes' if d.get('bridge',{}).get('bridge_ready') else 'no')
except:
    print('no')
" 2>/dev/null || echo "no")
    if [ "$_bridge_ready" = "yes" ]; then
      log GREEN "✓ Maven broker bridge ready (quote + order panel live)"
    else
      _panel_reason=$(echo "$_recover_resp" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print((d.get('bridge',{}).get('order_panel') or {}).get('reason','unknown'))
except:
    print('unavailable')
" 2>/dev/null || echo "unavailable")
      log YELLOW "⚠ Broker bridge not fully ready yet (reason: $_panel_reason)"
      log YELLOW "  If Maven needs login/Cloudflare challenge, complete it in the broker tab"
      log YELLOW "  then run: curl -X POST http://127.0.0.1:8000/status/broker_bridge/recover"
    fi
  else
    log YELLOW "⚠ Chrome may not be responding yet — broker bridge will attach on first trade tick"
  fi
fi

# Step 6: Live Sync Engine (Databento real-time candle feed → Redis)
if [ -f "$WORKSPACE/start_live_sync.py" ] && [ -n "$DATABENTO_API_KEY" ]; then
  if [ -f "$LIVESYNC_DISABLE_MARKER" ]; then
    log YELLOW "⚠ Live sync disabled: $(cat "$LIVESYNC_DISABLE_MARKER" 2>/dev/null || echo databento_auth_failure)"
    log YELLOW "  Fix DATABENTO_API_KEY and remove $LIVESYNC_DISABLE_MARKER to re-enable live sync"
  else
    log BLUE "Starting Databento live sync engine..."
    pkill -f "start_live_sync.py" 2>/dev/null || true
    sleep 1
    nohup env PYTHONUNBUFFERED=1 python "$WORKSPACE/start_live_sync.py" >> "$LOG_DIR/livesync.log" 2>&1 &
    sleep 3
    if pgrep -f "start_live_sync.py" > /dev/null; then
      log GREEN "✓ Live sync engine running (candles → Redis)"
    elif [ -f "$LIVESYNC_DISABLE_MARKER" ]; then
      log YELLOW "⚠ Live sync disabled after startup: $(cat "$LIVESYNC_DISABLE_MARKER" 2>/dev/null || echo databento_auth_failure)"
    else
      log YELLOW "⚠ Live sync engine failed to start — check $LOG_DIR/livesync.log"
    fi
  fi
else
  if [ -z "$DATABENTO_API_KEY" ]; then
    log YELLOW "⚠ DATABENTO_API_KEY not set — live sync skipped (chart will use historical fallback)"
  fi
fi

# Step 7: MT5 bridge sync (MetaEditor CSV -> canonical timeframe datasets)
if [ -f "$WORKSPACE/start_mt5_bridge_sync.sh" ]; then
  if [ -x "$WORKSPACE/ingest_mt5_feed_from_drop.sh" ]; then
    log BLUE "Running MT5 drop ingest pre-sync..."
    bash "$WORKSPACE/ingest_mt5_feed_from_drop.sh" >> "$LOG_DIR/mt5_bridge_sync.log" 2>&1 || true
  fi
  log BLUE "Starting MT5 bridge sync daemon..."
  bash "$WORKSPACE/start_mt5_bridge_sync.sh" >> "$LOG_DIR/mt5_bridge_sync.log" 2>&1 || true
  sleep 2
  if [ -x "$WORKSPACE/status_mt5_bridge_sync.sh" ]; then
    if bash "$WORKSPACE/status_mt5_bridge_sync.sh" > /tmp/astroquant_mt5_bridge_status.out 2>&1; then
      log GREEN "✓ MT5 bridge sync running"
    else
      _mt5_status_msg="$(cat /tmp/astroquant_mt5_bridge_status.out 2>/dev/null || echo 'status check failed')"
      log YELLOW "⚠ MT5 bridge sync status warning: $_mt5_status_msg"
    fi
  else
    log GREEN "✓ MT5 bridge sync start command issued"
  fi
else
  log YELLOW "⚠ start_mt5_bridge_sync.sh not found — MT5 bridge sync skipped"
fi

# Step 7b: MT5 stooq fallback feeder (keeps feed alive when Windows MT5 is offline)
if pgrep -f "mt5_stooq_fallback_feeder" > /dev/null 2>&1; then
  log GREEN "✓ MT5 stooq fallback feeder already running"
else
  log BLUE "Starting MT5 stooq fallback feeder (24/7 auto-synthesise)..."
  nohup "$WORKSPACE/.venv/bin/python3" "$WORKSPACE/tools/mt5_stooq_fallback_feeder.py" \
    >> "$LOG_DIR/mt5_stooq_fallback.log" 2>&1 &
  sleep 1
  if pgrep -f "mt5_stooq_fallback_feeder" > /dev/null 2>&1; then
    log GREEN "✓ MT5 stooq fallback feeder started (PID: $(pgrep -f mt5_stooq_fallback_feeder))"
  else
    log YELLOW "⚠ MT5 stooq fallback feeder failed to start — check $LOG_DIR/mt5_stooq_fallback.log"
  fi
fi

# Step 8: CF Auto-Unblock
log BLUE "Starting Cloudflare challenge auto-unblock..."
nohup python cloudflare_unblock.py > "$LOG_DIR/cf_unblock.log" 2>&1 &
sleep 2
log GREEN "✓ CF unblock monitor started"

# Step 9: Cloudflare Tunnel (optional)
if [ "$NO_TUNNEL" != true ]; then
  log BLUE "Starting Cloudflare Tunnel for remote access..."
  bash start_cloudflare_tunnel.sh 2>&1 | tee -a "$LOG_DIR/fullstack.log" &
  sleep 5
  
  TUNNEL_URL=$(cat "$DATA_DIR/tunnel_url.txt" 2>/dev/null || echo "PENDING")
  log GREEN "✓ Tunnel ready: $TUNNEL_URL"
fi

# Step 10: NoVPN Connector (optional)
if [ "$NO_NOVPN" != true ]; then
  log BLUE "Starting VNC desktop backend for noVNC..."
  bash start_vnc_desktop.sh 2>&1 | tee -a "$LOG_DIR/fullstack.log" &
  sleep 2

  log BLUE "Starting noVNC connector (if available)..."
  bash start_novpn_connector.sh 2>&1 | tee -a "$LOG_DIR/fullstack.log" &
  sleep 3
  NOVPN_URL=$(cat "$DATA_DIR/novpn_url.txt" 2>/dev/null || echo "PENDING")
  NOVNC_URL=$(cat "$DATA_DIR/novnc_url.txt" 2>/dev/null || echo "PENDING")
  log GREEN "✓ noVNC status: $NOVNC_URL"

  # Start dedicated Cloudflare tunnel for noVNC UI if local noVNC is up.
  if [ -f "$DATA_DIR/novnc.pid" ] && kill -0 "$(cat "$DATA_DIR/novnc.pid")" 2>/dev/null; then
    log BLUE "Starting Cloudflare Tunnel for noVNC remote desktop..."
    bash start_cloudflare_tunnel_novnc.sh 2>&1 | tee -a "$LOG_DIR/fullstack.log" &
    sleep 3
    NOVNC_CF_URL=$(cat "$DATA_DIR/novnc_tunnel_url.txt" 2>/dev/null || echo "PENDING")
    log GREEN "✓ noVNC Cloudflare URL: $NOVNC_CF_URL"
  fi
fi

# Summary
echo ""
log GREEN "========================================="
log GREEN "✓ Full Stack Ready!"
log GREEN "========================================="
log GREEN "Local Dashboard: http://127.0.0.1:8000/frontend/"
log GREEN "Backend Status: http://127.0.0.1:8000/status"
log GREEN "Redis: 127.0.0.1:6379"
log GREEN "Chrome CDP: 127.0.0.1:9222"
[ "$NO_TUNNEL" != true ] && log GREEN "Remote Access: $(cat $DATA_DIR/tunnel_url.txt 2>/dev/null || echo 'PENDING')"
[ "$NO_NOVPN" != true ] && log GREEN "NoVPN Access: $(cat $DATA_DIR/novpn_url.txt 2>/dev/null || echo 'PENDING')"
[ "$NO_NOVPN" != true ] && log GREEN "noVNC Access: $(cat $DATA_DIR/novnc_url.txt 2>/dev/null || echo 'PENDING')"
[ "$NO_NOVPN" != true ] && log GREEN "noVNC Cloudflare: $(cat $DATA_DIR/novnc_tunnel_url.txt 2>/dev/null || echo 'PENDING')"

# Telegram daemon (chat commands + reports + signal/news alerts)
if [ "${TELEGRAM_ALERT_ENABLED:-false}" = "true" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
  log BLUE "Starting Telegram daemon..."
  pkill -f "$WORKSPACE/telegram_bot_daemon.py" 2>/dev/null || true
  sleep 1
  nohup python "$WORKSPACE/telegram_bot_daemon.py" > "$LOG_DIR/telegram_daemon.runtime.log" 2>&1 &
  sleep 2
  if pgrep -f "$WORKSPACE/telegram_bot_daemon.py" > /dev/null; then
    log GREEN "✓ Telegram daemon running"
  else
    log YELLOW "⚠ Telegram daemon failed to start"
  fi
else
  log YELLOW "⚠ Telegram daemon skipped (set TELEGRAM_ALERT_ENABLED=true + token/chat_id)"
fi

log GREEN "========================================="
log GREEN "Logs: $LOG_DIR/"
log GREEN "========================================="
echo ""

# Wait for Cloudflare tunnel URL to be captured before sending startup alert.
# Quick tunnels take 10-30 s to connect and write the URL to tunnel_url.txt.
if [ "${NO_TUNNEL}" != true ]; then
  log BLUE "Waiting for Cloudflare tunnel URL (max 45s)..."
  _tunnel_wait=0
  while [ $_tunnel_wait -lt 45 ]; do
    _turl=$(cat "$DATA_DIR/tunnel_url.txt" 2>/dev/null || true)
    if echo "$_turl" | grep -q "trycloudflare\.com\|cloudflare"; then
      log GREEN "✓ Tunnel URL ready: $_turl"
      break
    fi
    sleep 3
    _tunnel_wait=$((_tunnel_wait + 3))
  done
  if [ $_tunnel_wait -ge 45 ]; then
    log YELLOW "⚠ Tunnel URL not available after 45s — startup alert will show PENDING"
  fi
fi

# Send startup/reboot alert with current remote URLs if configured.
bash "$WORKSPACE/send_telegram_alert.sh" reboot-startup >> "$LOG_DIR/fullstack.log" 2>&1 || true

# Health check loop
log BLUE "Starting health monitoring (interval: ${HEALTHCHECK_INTERVAL}s)..."
echo ""

while true; do
  sleep "$HEALTHCHECK_INTERVAL"
  
  # Check Redis
  if ! redis-cli ping > /dev/null 2>&1; then
    log RED "✗ Redis down! Restarting..."
    redis-server --daemonize yes --logfile "$LOG_DIR/redis.log"
  fi
  
  # Check Celery
  if ! pgrep -f "celery.*worker" > /dev/null; then
    log RED "✗ Celery down! Restarting..."
    cd "$WORKSPACE"
    _AQ_CELERY_CONCUR="${CELERY_CONCURRENCY:-$(python3 -c "import os; print(min(8, max(4, (os.cpu_count() or 4) * 2)))" 2>/dev/null || echo 4)}"
    nohup celery -A astroquant.backend.tasks.celery_worker:celery_app worker \
      --loglevel=info \
      --logfile="$LOG_DIR/celery.log" \
      --pidfile="$LOG_DIR/celery.pid" \
      --pool=threads \
      --concurrency="$_AQ_CELERY_CONCUR" \
      > "$LOG_DIR/celery.log" 2>&1 &
  fi

  # Check Live Sync Engine (Databento candle feed)
  if [ -f "$WORKSPACE/start_live_sync.py" ] && [ -n "$DATABENTO_API_KEY" ]; then
    if [ -f "$LIVESYNC_DISABLE_MARKER" ]; then
      :
    elif ! pgrep -f "start_live_sync.py" > /dev/null; then
      log RED "✗ Live sync engine down! Restarting..."
      nohup env PYTHONUNBUFFERED=1 python "$WORKSPACE/start_live_sync.py" >> "$LOG_DIR/livesync.log" 2>&1 &
    fi
  fi

  # Check Orchestrator
  ORCH_PIDS="$(pgrep -f "python .*start_astroquant.py|/start_astroquant.py" || true)"
  ORCH_COUNT="$(printf "%s\n" "$ORCH_PIDS" | sed '/^$/d' | wc -l)"
  if [ "$ORCH_COUNT" -gt 1 ]; then
    log RED "✗ Orchestrator duplicate instances detected ($ORCH_COUNT). Restarting singleton..."
    pkill -f "python .*start_astroquant.py|/start_astroquant.py" 2>/dev/null || true
    sleep 1
    nohup python "$WORKSPACE/start_astroquant.py" > "$LOG_DIR/orchestrator.log" 2>&1 &
    echo $! > "$LOG_DIR/orchestrator.pid"
    sleep 3
  elif [ "$ORCH_COUNT" -eq 0 ]; then
    log RED "✗ Orchestrator down! Restarting..."
    nohup python "$WORKSPACE/start_astroquant.py" > "$LOG_DIR/orchestrator.log" 2>&1 &
    echo $! > "$LOG_DIR/orchestrator.pid"
    sleep 3
  fi
  
  # Check Backend — restart only when health endpoints fail.
  if ! curl -fsS http://127.0.0.1:8000/health > /dev/null 2>&1 \
       && ! curl -fsS http://127.0.0.1:8000/status/feed > /dev/null 2>&1; then
    log RED "✗ Backend down! Restarting..."
    pkill -f "uvicorn.*main:app" 2>/dev/null || true
    sleep 2
    cd "$WORKSPACE"
    _AQ_WORKERS="${FASTAPI_WORKERS:-1}"
    _AQ_LOG_LEVEL="${FASTAPI_LOG_LEVEL:-warning}"
    export MCL_CHART_PROCESS_POOL_ENABLED="${MCL_CHART_PROCESS_POOL_ENABLED:-1}"
    export MCL_CHART_PROCESS_POOL_MAX_WORKERS="${MCL_CHART_PROCESS_POOL_MAX_WORKERS:-2}"
    export MCL_CHART_PROCESS_POOL_TIMEOUT_SECONDS="${MCL_CHART_PROCESS_POOL_TIMEOUT_SECONDS:-40}"
    export MCL_CHART_PROCESS_POOL_START_METHOD="${MCL_CHART_PROCESS_POOL_START_METHOD:-spawn}"
    export MCL_CHART_PREWARM_ENABLED="${MCL_CHART_PREWARM_ENABLED:-1}"
    export MCL_CHART_PREWARM_DELAY_SECONDS="${MCL_CHART_PREWARM_DELAY_SECONDS:-3}"
    export MCL_CHART_PREWARM_SPECS="${MCL_CHART_PREWARM_SPECS:-XAUUSD:5m:realtime:1800:1,XAUUSD:15m:balanced:2200:2,XAUUSD:1h:balanced:3200:3,XAUUSD:4h:balanced:4200:5,XAUUSD:1d:deep:12000:15}"
    nohup python -m uvicorn astroquant.backend.main:app \
      --host 0.0.0.0 \
      --port 8000 \
      --workers "$_AQ_WORKERS" \
      --log-level "$_AQ_LOG_LEVEL" \
      > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$LOG_DIR/backend.pid"
    sleep 3
  fi
  
  # Check Chrome (optional)
  if [ "$NO_CHROME" != true ]; then
    if ! curl -s http://127.0.0.1:9222/json/version > /dev/null 2>&1; then
      log YELLOW "⚠ Chrome not responding — restarting..."
      pkill -f "chrome.*remote-debugging-port=9222" 2>/dev/null || true
      sleep 1
      DISPLAY="${DISPLAY:-${AQ_XVFB_DISPLAY:-:99}}" \
      AQ_WORKSPACE="$WORKSPACE" \
      AQ_API_BASE="http://127.0.0.1:8000" \
      AQ_CHROME_PROFILE_DIR="$DATA_DIR/browser_session/chrome-profile" \
      AQ_XVFB_DISPLAY="${AQ_XVFB_DISPLAY:-:99}" \
      AQ_USE_XVFB="${AQ_USE_XVFB:-true}" \
      nohup bash "$WORKSPACE/start_chrome_remote_debug.sh" >> "$LOG_DIR/chrome.log" 2>&1 &
    fi
  fi

  # Check Cloudflare tunnel (optional)
  if [ "$NO_TUNNEL" != true ]; then
    if ! pgrep -f "cloudflared tunnel --url http://localhost:8000" > /dev/null; then
      log RED "✗ Cloudflare tunnel down! Restarting..."
      bash start_cloudflare_tunnel.sh >> "$LOG_DIR/fullstack.log" 2>&1 &
      sleep 5
      bash "$WORKSPACE/send_telegram_alert.sh" app-link-rotated >> "$LOG_DIR/fullstack.log" 2>&1 || true
    fi
  fi

  # Check NoVPN connector (optional)
  if [ "$NO_NOVPN" != true ]; then
    NOVPN_PID_FILE="$DATA_DIR/novpn.pid"
    if [ -f "$NOVPN_PID_FILE" ] && ! kill -0 "$(cat "$NOVPN_PID_FILE")" 2>/dev/null; then
      log RED "✗ NoVPN connector down! Restarting..."
      bash start_novpn_connector.sh >> "$LOG_DIR/fullstack.log" 2>&1 &
    fi

    if ! ss -ltn | grep -q ':5901'; then
      log RED "✗ VNC backend not listening on 5901! Restarting..."
      bash start_vnc_desktop.sh >> "$LOG_DIR/fullstack.log" 2>&1 &
    fi

    NOVNC_PID_FILE="$DATA_DIR/novnc.pid"
    if [ -f "$NOVNC_PID_FILE" ] && ! kill -0 "$(cat "$NOVNC_PID_FILE")" 2>/dev/null; then
      log RED "✗ noVNC connector down! Restarting..."
      bash start_novpn_connector.sh >> "$LOG_DIR/fullstack.log" 2>&1 &
    fi

    if [ -f "$DATA_DIR/novnc.pid" ] && kill -0 "$(cat "$DATA_DIR/novnc.pid")" 2>/dev/null; then
      if ! pgrep -f "cloudflared tunnel --url http://localhost:6080" > /dev/null; then
        log RED "✗ noVNC Cloudflare tunnel down! Restarting..."
        bash start_cloudflare_tunnel_novnc.sh >> "$LOG_DIR/fullstack.log" 2>&1 &
        sleep 5
        bash "$WORKSPACE/send_telegram_alert.sh" desktop-link-rotated >> "$LOG_DIR/fullstack.log" 2>&1 || true
      fi
    fi
  fi

  # Check Telegram daemon only when enabled/configured.
  if [ "${TELEGRAM_ALERT_ENABLED:-false}" = "true" ] && [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_CHAT_ID:-}" ]; then
    TELEGRAM_PIDS="$(pgrep -f "$WORKSPACE/telegram_bot_daemon.py" || true)"
    TELEGRAM_COUNT="$(printf "%s\n" "$TELEGRAM_PIDS" | sed '/^$/d' | wc -l)"

    if [ "$TELEGRAM_COUNT" -gt 1 ]; then
      log RED "✗ Telegram daemon duplicate instances detected ($TELEGRAM_COUNT). Restarting singleton..."
      pkill -f "$WORKSPACE/telegram_bot_daemon.py" 2>/dev/null || true
      sleep 1
      nohup python "$WORKSPACE/telegram_bot_daemon.py" > "$LOG_DIR/telegram_daemon.runtime.log" 2>&1 &
    elif [ "$TELEGRAM_COUNT" -eq 0 ]; then
      log RED "✗ Telegram daemon down! Restarting..."
      pkill -f "$WORKSPACE/telegram_bot_daemon.py" 2>/dev/null || true
      sleep 1
      nohup python "$WORKSPACE/telegram_bot_daemon.py" > "$LOG_DIR/telegram_daemon.runtime.log" 2>&1 &
    fi
  fi
done
