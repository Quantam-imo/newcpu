#!/bin/bash
# Non-systemd autostart bootstrap for container-like environments.
# Safe to run repeatedly; starts AstroQuant only when core stack is down.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
LOG_DIR="$WORKSPACE/data/logs"
LOCK_FILE="/tmp/astroquant_non_systemd_autostart.lock"

mkdir -p "$LOG_DIR"

# PID-file-based duplicate prevention: does not use file descriptors that
# could be inherited by daemonized child processes (e.g. redis-server).
if [ -f "$LOCK_FILE" ]; then
  _old_pid="$(cat "$LOCK_FILE" 2>/dev/null)"
  if [ -n "$_old_pid" ] && kill -0 "$_old_pid" 2>/dev/null; then
    # Previous bootstrap is still running — skip
    exit 0
  fi
  rm -f "$LOCK_FILE"
fi
echo $$ > "$LOCK_FILE"
# Remove lockfile on exit so future runs are never blocked
trap 'rm -f "$LOCK_FILE"' EXIT

if pgrep -f "start_24h_fullstack.sh" >/dev/null 2>&1; then
  exit 0
fi

if pgrep -f "python -m uvicorn astroquant.backend.main:app" >/dev/null 2>&1; then
  exit 0
fi

if [ ! -x "$WORKSPACE/npvps_auto_start.sh" ]; then
  exit 0
fi

nohup /bin/bash "$WORKSPACE/npvps_auto_start.sh" >> "$LOG_DIR/reboot_autostart.log" 2>&1 &
