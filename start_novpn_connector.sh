#!/bin/bash
# Start noVNC connector (remote desktop over web) if package is present.
# Backward compatible with legacy NoVPN executable mode.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
DATA_DIR="$WORKSPACE/data"
LOG_DIR="$DATA_DIR/logs"
NOVPN_ROOT="$WORKSPACE/tools/novpn"
NOVPN_PID_FILE="$DATA_DIR/novpn.pid"
NOVPN_LOG="$LOG_DIR/novpn.log"
NOVPN_URL_FILE="$DATA_DIR/novpn_url.txt"

NOVNC_ROOT="$WORKSPACE/tools/novnc"
NOVNC_PID_FILE="$DATA_DIR/novnc.pid"
NOVNC_LOG="$LOG_DIR/novnc.log"
NOVNC_URL_FILE="$DATA_DIR/novnc_url.txt"
NOVNC_WEB_AUTH_FILE="$DATA_DIR/novnc_web_auth.txt"

mkdir -p "$LOG_DIR" "$NOVPN_ROOT" "$NOVNC_ROOT"

echo "[$(date)] Starting noVNC/NoVPN connector..." | tee -a "$NOVPN_LOG"

# noVNC mode (preferred)
if [ -f "$NOVNC_PID_FILE" ] && kill -0 "$(cat "$NOVNC_PID_FILE")" 2>/dev/null; then
  echo "[$(date)] noVNC already running (PID: $(cat "$NOVNC_PID_FILE"))" | tee -a "$NOVNC_LOG"
  cat "$NOVNC_URL_FILE" 2>/dev/null || true
  exit 0
fi

# If pid file is missing/stale but proxy is already running, reuse it.
NOVNC_EXISTING_PID=$(pgrep -f "novnc_proxy --listen ${NOVNC_LISTEN:-6080}" | head -1 || true)
if [ -n "$NOVNC_EXISTING_PID" ] && kill -0 "$NOVNC_EXISTING_PID" 2>/dev/null; then
  echo "$NOVNC_EXISTING_PID" > "$NOVNC_PID_FILE"
  echo "http://127.0.0.1:${NOVNC_LISTEN:-6080}/vnc.html" > "$NOVNC_URL_FILE"
  echo "[$(date)] noVNC already running (PID: $NOVNC_EXISTING_PID)" | tee -a "$NOVNC_LOG"
  cat "$NOVNC_URL_FILE"
  exit 0
fi

NOVNC_DIR_CANDIDATE=$(find "$WORKSPACE" "$HOME" -maxdepth 5 -type d -iname "noVNC*" 2>/dev/null | head -1 || true)
NOVNC_ZIP_CANDIDATE=$(find "$WORKSPACE" "$HOME" -maxdepth 5 -type f \( -iname "*novnc*.zip" -o -iname "*noVNC*.zip" \) 2>/dev/null | head -1 || true)

if [ -n "$NOVNC_ZIP_CANDIDATE" ]; then
  unzip -o "$NOVNC_ZIP_CANDIDATE" -d "$NOVNC_ROOT" >> "$NOVNC_LOG" 2>&1 || true
  NOVNC_DIR_CANDIDATE=$(find "$NOVNC_ROOT" -maxdepth 5 -type d -iname "noVNC*" 2>/dev/null | head -1 || true)
fi

NOVNC_PROXY=""
if [ -n "$NOVNC_DIR_CANDIDATE" ]; then
  NOVNC_PROXY=$(find "$NOVNC_DIR_CANDIDATE" -maxdepth 4 -type f -name "novnc_proxy" 2>/dev/null | head -1 || true)
fi

if [ -n "$NOVNC_PROXY" ]; then
  chmod +x "$NOVNC_PROXY" 2>/dev/null || true
  NOVNC_LISTEN="${NOVNC_LISTEN:-6080}"
  NOVNC_VNC_TARGET="${NOVNC_VNC_TARGET:-127.0.0.1:5901}"

  # Protect noVNC web endpoint with HTTP basic auth.
  if [ -n "${NOVNC_WEB_USER:-}" ] && [ -n "${NOVNC_WEB_PASS:-}" ]; then
    NOVNC_AUTH_SOURCE="${NOVNC_WEB_USER}:${NOVNC_WEB_PASS}"
  elif [ -f "$NOVNC_WEB_AUTH_FILE" ]; then
    NOVNC_AUTH_SOURCE="$(cat "$NOVNC_WEB_AUTH_FILE")"
  else
    NOVNC_WEB_USER="aqadmin"
    NOVNC_WEB_PASS="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)"
    NOVNC_AUTH_SOURCE="${NOVNC_WEB_USER}:${NOVNC_WEB_PASS}"
    echo "$NOVNC_AUTH_SOURCE" > "$NOVNC_WEB_AUTH_FILE"
    chmod 600 "$NOVNC_WEB_AUTH_FILE"
  fi

  (
    "$NOVNC_PROXY" \
      --listen "$NOVNC_LISTEN" \
      --vnc "$NOVNC_VNC_TARGET" \
      --web-auth \
      --auth-plugin BasicHTTPAuth \
      --auth-source "$NOVNC_AUTH_SOURCE" \
      2>&1 | tee -a "$NOVNC_LOG"
  ) &
  NOVNC_PID=$!
  echo "$NOVNC_PID" > "$NOVNC_PID_FILE"

  sleep 3
  if kill -0 "$NOVNC_PID" 2>/dev/null; then
    echo "http://127.0.0.1:${NOVNC_LISTEN}/vnc.html" > "$NOVNC_URL_FILE"
    echo "[$(date)] noVNC started (PID: $NOVNC_PID)" | tee -a "$NOVNC_LOG"
    cat "$NOVNC_URL_FILE"
    exit 0
  else
    echo "[$(date)] noVNC failed to start; falling back to legacy NoVPN mode" | tee -a "$NOVNC_LOG"
  fi
fi

if [ -f "$NOVPN_PID_FILE" ] && kill -0 "$(cat "$NOVPN_PID_FILE")" 2>/dev/null; then
  echo "[$(date)] NoVPN already running (PID: $(cat "$NOVPN_PID_FILE"))" | tee -a "$NOVPN_LOG"
  cat "$NOVPN_URL_FILE" 2>/dev/null || true
  exit 0
fi

# Optional explicit executable path.
if [ -n "${NOVPN_EXECUTABLE:-}" ] && [ -x "${NOVPN_EXECUTABLE}" ]; then
  BIN_PATH="${NOVPN_EXECUTABLE}"
else
  BIN_PATH=""
fi

# Find downloaded zip if executable not already known.
if [ -z "$BIN_PATH" ]; then
  ZIP_CANDIDATE=$(find "$WORKSPACE" "$HOME" -maxdepth 5 -type f -iname "*novpn*.zip" 2>/dev/null | head -1 || true)
  if [ -n "$ZIP_CANDIDATE" ]; then
    unzip -o "$ZIP_CANDIDATE" -d "$NOVPN_ROOT" >> "$NOVPN_LOG" 2>&1 || true
  fi

  BIN_PATH=$(find "$NOVPN_ROOT" -maxdepth 5 -type f \( -iname "novpn" -o -iname "novpn-cli" -o -iname "*novpn*" \) -perm -111 2>/dev/null | head -1 || true)
fi

if [ -z "$BIN_PATH" ]; then
  echo "[$(date)] NoVPN executable not found. Skipping legacy NoVPN startup." | tee -a "$NOVPN_LOG"
  echo "[$(date)] Expected noVNC zip/dir or set NOVPN_EXECUTABLE for legacy mode." | tee -a "$NOVPN_LOG"
  exit 0
fi

chmod +x "$BIN_PATH" 2>/dev/null || true

# Default args can be overridden with NOVPN_ARGS.
NOVPN_ARGS_DEFAULT=""
NOVPN_ARGS="${NOVPN_ARGS:-$NOVPN_ARGS_DEFAULT}"

(
  "$BIN_PATH" $NOVPN_ARGS 2>&1 | tee -a "$NOVPN_LOG"
) &
NOVPN_PID=$!
echo "$NOVPN_PID" > "$NOVPN_PID_FILE"

sleep 3
if kill -0 "$NOVPN_PID" 2>/dev/null; then
  URL_FROM_LOG=$(grep -Eo 'https?://[^ ]+' "$NOVPN_LOG" | tail -1 || true)
  if [ -n "$URL_FROM_LOG" ]; then
    echo "$URL_FROM_LOG" > "$NOVPN_URL_FILE"
  fi
  echo "[$(date)] NoVPN started (PID: $NOVPN_PID)" | tee -a "$NOVPN_LOG"
  [ -n "$URL_FROM_LOG" ] && echo "$URL_FROM_LOG"
else
  echo "[$(date)] NoVPN failed to start" | tee -a "$NOVPN_LOG"
  exit 1
fi
