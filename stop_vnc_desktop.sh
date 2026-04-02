#!/bin/bash
# Stop lightweight desktop session used by noVNC.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
DATA_DIR="$WORKSPACE/data"

for f in x11vnc.pid fluxbox.pid xvfb.pid; do
  PID_FILE="$DATA_DIR/$f"
  if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$PID" ]; then
      kill "$PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi
done

pkill -f "x11vnc.*:1" 2>/dev/null || true
pkill -f "Xvfb :1" 2>/dev/null || true
pkill -f fluxbox 2>/dev/null || true
pkill -f "xterm.*AstroQuant CPU" 2>/dev/null || true

echo "VNC desktop stopped"
