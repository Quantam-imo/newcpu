#!/bin/bash
# Start MT5 drop ingest watcher in clean background mode.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WATCH_SCRIPT="$ROOT_DIR/watch_mt5_drop_ingest.sh"
PID_FILE="/tmp/astroquant_mt5_drop_ingest_watch.pid"
LOG_FILE="/tmp/astroquant_mt5_drop_ingest_watch.log"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "MT5 drop ingest watcher already running (PID: $old_pid)"
    echo "Log: $LOG_FILE"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

if [[ ! -x "$WATCH_SCRIPT" ]]; then
  chmod +x "$WATCH_SCRIPT"
fi

nohup bash -c '
  set -euo pipefail
  echo $$ > "'$PID_FILE'"
  trap "rm -f \"'$PID_FILE'\"" EXIT
  "'$WATCH_SCRIPT'" >> "'$LOG_FILE'" 2>&1
' >/dev/null 2>&1 &

sleep 1
if [[ -f "$PID_FILE" ]]; then
  echo "MT5 drop ingest watcher started (PID: $(cat "$PID_FILE"))"
  echo "Log: $LOG_FILE"
else
  echo "ERROR: failed to start MT5 drop ingest watcher"
  exit 1
fi
