#!/bin/bash
# Start Cloudflare Tunnel for permanent remote CPU access
# This script runs the tunnel in the background and logs to file

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"

CF_TUNNEL_MODE="${CF_TUNNEL_MODE:-quick}"
TUNNEL_NAME="${CF_APP_TUNNEL_NAME:-astroquant-cpu}"
CF_APP_PUBLIC_URL="${CF_APP_PUBLIC_URL:-}"
LOG_FILE="$WORKSPACE/data/logs/cloudflare_tunnel.log"
TUNNEL_URL_FILE="$WORKSPACE/data/tunnel_url.txt"
PID_FILE="$WORKSPACE/data/cloudflare_tunnel.pid"

mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$TUNNEL_URL_FILE")"

echo "[$(date)] Starting Cloudflare Tunnel for AstroQuant remote access..." | tee -a "$LOG_FILE"

if [ "$CF_TUNNEL_MODE" = "named" ]; then
  EXISTING_PID=$(pgrep -f "cloudflared tunnel run $TUNNEL_NAME" | head -1 || true)
  if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "$EXISTING_PID" > "$PID_FILE"
    if [ -n "$CF_APP_PUBLIC_URL" ]; then
      echo "$CF_APP_PUBLIC_URL" > "$TUNNEL_URL_FILE"
    else
      echo "NAMED_TUNNEL_RUNNING:$TUNNEL_NAME" > "$TUNNEL_URL_FILE"
    fi
    echo "[$(date)] Named tunnel already running (PID: $EXISTING_PID)" | tee -a "$LOG_FILE"
    cat "$TUNNEL_URL_FILE"
    exit 0
  fi

  (
    cloudflared tunnel run "$TUNNEL_NAME" 2>&1 | tee -a "$LOG_FILE"
  ) &
  TUNNEL_PID=$!
  echo "$TUNNEL_PID" > "$PID_FILE"
  sleep 3

  if kill -0 "$TUNNEL_PID" 2>/dev/null; then
    if [ -n "$CF_APP_PUBLIC_URL" ]; then
      echo "$CF_APP_PUBLIC_URL" > "$TUNNEL_URL_FILE"
    else
      echo "NAMED_TUNNEL_RUNNING:$TUNNEL_NAME" > "$TUNNEL_URL_FILE"
    fi
    echo "[$(date)] Named tunnel is running (PID: $TUNNEL_PID)" | tee -a "$LOG_FILE"
    cat "$TUNNEL_URL_FILE"
    exit 0
  else
    echo "[$(date)] Failed to start named tunnel '$TUNNEL_NAME', falling back to quick tunnel" | tee -a "$LOG_FILE"
    CF_TUNNEL_MODE="quick"
  fi
fi

# If any cloudflared quick tunnel is already alive, reuse it.
EXISTING_PID=$(pgrep -f "cloudflared tunnel --url http://localhost:8000" | head -1 || true)
if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
  # Keep only one process to avoid duplicate tunnels.
  for pid in $(pgrep -f "cloudflared tunnel --url http://localhost:8000" || true); do
    if [ "$pid" != "$EXISTING_PID" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  echo "$EXISTING_PID" > "$PID_FILE"
  TUNNEL_URL=$(grep -o "https://[a-z0-9\-]*\.trycloudflare\.com" "$LOG_FILE" 2>/dev/null | tail -1 || true)
  if [ -n "$TUNNEL_URL" ]; then
    echo "$TUNNEL_URL" > "$TUNNEL_URL_FILE"
  fi
  echo "[$(date)] Tunnel already running (PID: $EXISTING_PID)" | tee -a "$LOG_FILE"
  cat "$TUNNEL_URL_FILE" 2>/dev/null || true
  exit 0
fi

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat $PID_FILE)" 2>/dev/null; then
  echo "[$(date)] Tunnel already running (PID: $(cat $PID_FILE))" | tee -a "$LOG_FILE"
  cat "$TUNNEL_URL_FILE" 2>/dev/null || true
  exit 0
fi

# Start tunnel with URL capture
(
  cloudflared tunnel --url http://localhost:8000 2>&1 | tee -a "$LOG_FILE"
) &

TUNNEL_PID=$!
echo $TUNNEL_PID > "$PID_FILE"

echo "[$(date)] Cloudflare Tunnel started (PID: $TUNNEL_PID)" | tee -a "$LOG_FILE"

# Wait a moment for tunnel to establish
sleep 3

# Check if tunnel is running
if kill -0 $TUNNEL_PID 2>/dev/null; then
  echo "[$(date)] ✓ Tunnel is running" | tee -a "$LOG_FILE"
  
  # Try to extract the public URL from logs
  TUNNEL_URL=$(grep -o "https://[a-z0-9\-]*\.trycloudflare\.com" "$LOG_FILE" 2>/dev/null | tail -1 || echo "PENDING")
  echo "[$(date)] Public URL: $TUNNEL_URL" | tee -a "$LOG_FILE"
  echo "$TUNNEL_URL" > "$TUNNEL_URL_FILE"
  
  echo ""
  echo "========================================="
  echo "Cloudflare Tunnel Ready!"
  echo "========================================="
  echo "Remote Access URL: $TUNNEL_URL"
  echo "Local Dashboard: http://localhost:8000/frontend/"
  echo "Logs: tail -f $LOG_FILE"
  echo "========================================="
else
  echo "[$(date)] ✗ Failed to start tunnel" | tee -a "$LOG_FILE"
  exit 1
fi

wait $TUNNEL_PID
