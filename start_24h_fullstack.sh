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
HEALTHCHECK_INTERVAL=30
STARTUP_TIMEOUT=60
NO_CHROME=false
NO_TUNNEL=false
NO_NOVPN=false

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
redis-server --daemonize yes --logfile "$LOG_DIR/redis.log" 2>/dev/null || true
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
nohup celery -A astroquant.backend.tasks.celery_worker:celery_app worker \
  --loglevel=info \
  --logfile="$LOG_DIR/celery.log" \
  --pidfile="$LOG_DIR/celery.pid" \
  --pool=threads \
  --concurrency=4 \
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
nohup python -m uvicorn astroquant.backend.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info \
  > "$LOG_DIR/backend.log" 2>&1 &

# Retry up to 45 seconds — cold boot takes longer than 6s
_backend_ok=false
for _i in 1 2 3 4 5 6 7 8 9; do
  sleep 5
  if curl -s http://127.0.0.1:8000/status > /dev/null 2>&1; then
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

  AQ_WORKSPACE="$WORKSPACE" \
  AQ_API_BASE="http://127.0.0.1:8000" \
  AQ_CHROME_PROFILE_DIR="$DATA_DIR/browser_session/chrome-profile" \
  nohup bash "$WORKSPACE/start_chrome_remote_debug.sh" > "$LOG_DIR/chrome.log" 2>&1 &
  
  sleep 6
  if curl -s http://127.0.0.1:9222/json/version > /dev/null 2>&1; then
    log GREEN "✓ Chrome CDP listening on port 9222"
  else
    log YELLOW "⚠ Chrome may not be responding yet"
  fi
fi

# Step 6: CF Auto-Unblock
log BLUE "Starting Cloudflare challenge auto-unblock..."
nohup python cloudflare_unblock.py > "$LOG_DIR/cf_unblock.log" 2>&1 &
sleep 2
log GREEN "✓ CF unblock monitor started"

# Step 7: Cloudflare Tunnel (optional)
if [ "$NO_TUNNEL" != true ]; then
  log BLUE "Starting Cloudflare Tunnel for remote access..."
  bash start_cloudflare_tunnel.sh 2>&1 | tee -a "$LOG_DIR/fullstack.log" &
  sleep 5
  
  TUNNEL_URL=$(cat "$DATA_DIR/tunnel_url.txt" 2>/dev/null || echo "PENDING")
  log GREEN "✓ Tunnel ready: $TUNNEL_URL"
fi

# Step 8: NoVPN Connector (optional)
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
    nohup celery -A astroquant.backend.tasks.celery_worker:celery_app worker \
      --loglevel=info \
      --logfile="$LOG_DIR/celery.log" \
      --pidfile="$LOG_DIR/celery.pid" \
      --pool=threads \
      --concurrency=4 \
      > "$LOG_DIR/celery.log" 2>&1 &
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
  
  # Check Backend
  if ! curl -s http://127.0.0.1:8000/status > /dev/null 2>&1; then
    log RED "✗ Backend down! Restarting..."
    pkill -f "uvicorn.*main:app" || true
    sleep 2
    cd "$WORKSPACE"
    nohup python -m uvicorn astroquant.backend.main:app \
      --host 0.0.0.0 \
      --port 8000 \
      --log-level info \
      > "$LOG_DIR/backend.log" 2>&1 &
    sleep 3
  fi
  
  # Check Chrome (optional)
  if [ "$NO_CHROME" != true ]; then
    if ! curl -s http://127.0.0.1:9222/json/version > /dev/null 2>&1; then
      log YELLOW "⚠ Chrome not responding"
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
