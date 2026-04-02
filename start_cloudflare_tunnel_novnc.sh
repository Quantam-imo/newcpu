#!/bin/bash
# Start dedicated Cloudflare quick tunnel for noVNC web UI.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"

CF_TUNNEL_MODE="${CF_TUNNEL_MODE:-quick}"
TUNNEL_NAME="${CF_NOVNC_TUNNEL_NAME:-astroquant-novnc}"
CF_NOVNC_PUBLIC_URL="${CF_NOVNC_PUBLIC_URL:-}"

LOG_FILE="$WORKSPACE/data/logs/cloudflare_tunnel_novnc.log"
PID_FILE="$WORKSPACE/data/cloudflare_tunnel_novnc.pid"
URL_FILE="$WORKSPACE/data/novnc_tunnel_url.txt"

mkdir -p "$WORKSPACE/data/logs" "$WORKSPACE/data"

wait_for_new_quick_url() {
  local start_line="$1"
  local waited=0
  local url=""
  while [ "$waited" -lt 45 ]; do
    url=$(awk -v s="$start_line" 'NR>s {if (match($0, /https:\/\/[a-z0-9\-]*\.trycloudflare\.com/)) {print substr($0, RSTART, RLENGTH)}}' "$LOG_FILE" | tail -1)
    if [ -n "$url" ]; then
      echo "$url"
      return 0
    fi
    sleep 3
    waited=$((waited + 3))
  done
  return 1
}

echo "[$(date)] Starting Cloudflare Tunnel for noVNC (http://localhost:6080)..." | tee -a "$LOG_FILE"

if [ "$CF_TUNNEL_MODE" = "named" ]; then
  EXISTING_PID=$(pgrep -f "cloudflared tunnel run $TUNNEL_NAME" | head -1 || true)
  if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "$EXISTING_PID" > "$PID_FILE"
    if [ -n "$CF_NOVNC_PUBLIC_URL" ]; then
      echo "$CF_NOVNC_PUBLIC_URL" > "$URL_FILE"
    else
      echo "NAMED_TUNNEL_RUNNING:$TUNNEL_NAME" > "$URL_FILE"
    fi
    echo "[$(date)] noVNC named tunnel already running (PID: $EXISTING_PID)" | tee -a "$LOG_FILE"
    cat "$URL_FILE"
    exit 0
  fi

  (
    cloudflared tunnel run "$TUNNEL_NAME" 2>&1 | tee -a "$LOG_FILE"
  ) &
  PID=$!
  echo "$PID" > "$PID_FILE"
  sleep 4
  if kill -0 "$PID" 2>/dev/null; then
    if [ -n "$CF_NOVNC_PUBLIC_URL" ]; then
      echo "$CF_NOVNC_PUBLIC_URL" > "$URL_FILE"
    else
      echo "NAMED_TUNNEL_RUNNING:$TUNNEL_NAME" > "$URL_FILE"
    fi
    echo "[$(date)] noVNC named tunnel running (PID: $PID)" | tee -a "$LOG_FILE"
    cat "$URL_FILE"
    exit 0
  else
    echo "[$(date)] Failed to start noVNC named tunnel '$TUNNEL_NAME', falling back to quick tunnel" | tee -a "$LOG_FILE"
    CF_TUNNEL_MODE="quick"
  fi
fi

EXISTING_PID=$(pgrep -f "cloudflared tunnel --url http://localhost:6080" | head -1 || true)
if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
  echo "$EXISTING_PID" > "$PID_FILE"
  # Reuse last known URL file for an already-running process; avoid stale grep from old sessions.
  [ -f "$URL_FILE" ] || echo "PENDING" > "$URL_FILE"
  echo "[$(date)] noVNC tunnel already running (PID: $EXISTING_PID)" | tee -a "$LOG_FILE"
  cat "$URL_FILE" 2>/dev/null || true
  exit 0
fi

START_LINE=$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)
(
  cloudflared tunnel --url http://localhost:6080 2>&1 | tee -a "$LOG_FILE"
) &
PID=$!
echo "$PID" > "$PID_FILE"

sleep 4
if kill -0 "$PID" 2>/dev/null; then
  URL=$(wait_for_new_quick_url "$START_LINE" || echo "PENDING")
  echo "$URL" > "$URL_FILE"
  echo "[$(date)] noVNC tunnel running (PID: $PID) URL: $URL" | tee -a "$LOG_FILE"
  echo "$URL"
else
  echo "[$(date)] Failed to start noVNC tunnel" | tee -a "$LOG_FILE"
  exit 1
fi
