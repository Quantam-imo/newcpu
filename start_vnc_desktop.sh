#!/bin/bash
# Start lightweight desktop session for noVNC access.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
DATA_DIR="$WORKSPACE/data"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$LOG_DIR" "$DATA_DIR"

XVFB_PID_FILE="$DATA_DIR/xvfb.pid"
FLUXBOX_PID_FILE="$DATA_DIR/fluxbox.pid"
X11VNC_PID_FILE="$DATA_DIR/x11vnc.pid"

XVFB_LOG="$LOG_DIR/xvfb.log"
FLUXBOX_LOG="$LOG_DIR/fluxbox.log"
X11VNC_LOG="$LOG_DIR/x11vnc.log"

DISPLAY_NUM="${DISPLAY_NUM:-:1}"
VNC_PORT="${VNC_PORT:-5901}"
SCREEN_GEOMETRY="${SCREEN_GEOMETRY:-1920x1080x24}"
VNC_PASS_FILE="$DATA_DIR/x11vnc.pass"
VNC_PASS_TXT="$DATA_DIR/vnc_password.txt"

# Start virtual display if needed.
if [ -f "$XVFB_PID_FILE" ] && kill -0 "$(cat "$XVFB_PID_FILE")" 2>/dev/null; then
  :
else
  pkill -f "Xvfb $DISPLAY_NUM" 2>/dev/null || true
  nohup Xvfb "$DISPLAY_NUM" -screen 0 "$SCREEN_GEOMETRY" -ac +extension GLX +render -noreset > "$XVFB_LOG" 2>&1 &
  echo $! > "$XVFB_PID_FILE"
  sleep 1
fi

export DISPLAY="$DISPLAY_NUM"

# Start window manager.
if [ -f "$FLUXBOX_PID_FILE" ] && kill -0 "$(cat "$FLUXBOX_PID_FILE")" 2>/dev/null; then
  :
else
  nohup fluxbox > "$FLUXBOX_LOG" 2>&1 &
  echo $! > "$FLUXBOX_PID_FILE"
  sleep 1
fi

# Optional startup terminal for immediate work.
if ! pgrep -f "xterm.*AstroQuant CPU" > /dev/null; then
  nohup xterm -title "AstroQuant CPU" -geometry 120x35+20+20 > "$LOG_DIR/xterm.log" 2>&1 &
fi

# Start VNC bridge to display.
if [ -f "$X11VNC_PID_FILE" ] && kill -0 "$(cat "$X11VNC_PID_FILE")" 2>/dev/null; then
  :
else
  pkill -f "x11vnc.*$DISPLAY_NUM" 2>/dev/null || true

  # Enforce password auth. Use env if provided, otherwise reuse/generated stable password.
  if [ -n "${VNC_PASSWORD:-}" ]; then
    VNC_PASS_VALUE="$VNC_PASSWORD"
  elif [ -f "$VNC_PASS_TXT" ]; then
    VNC_PASS_VALUE="$(cat "$VNC_PASS_TXT")"
  else
    VNC_PASS_VALUE="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 14)"
    echo "$VNC_PASS_VALUE" > "$VNC_PASS_TXT"
    chmod 600 "$VNC_PASS_TXT"
  fi

  x11vnc -storepasswd "$VNC_PASS_VALUE" "$VNC_PASS_FILE" > /dev/null 2>&1
  chmod 600 "$VNC_PASS_FILE"
  nohup x11vnc -display "$DISPLAY_NUM" -rfbport "$VNC_PORT" -rfbauth "$VNC_PASS_FILE" -forever -shared -noxdamage > "$X11VNC_LOG" 2>&1 &
  echo $! > "$X11VNC_PID_FILE"
  sleep 1
fi

echo "DISPLAY=$DISPLAY_NUM"
echo "VNC_PORT=$VNC_PORT"
echo "VNC_TARGET=127.0.0.1:$VNC_PORT"
