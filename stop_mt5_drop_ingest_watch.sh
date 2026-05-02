#!/bin/bash
# Stop MT5 drop ingest watcher background process.
set -euo pipefail

PID_FILE="/tmp/astroquant_mt5_drop_ingest_watch.pid"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" || true
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" || true
    fi
    echo "Stopped MT5 drop ingest watcher (PID: $pid)"
  else
    echo "PID file found, but process not running"
  fi
  rm -f "$PID_FILE"
  exit 0
fi

echo "MT5 drop ingest watcher is not running"
exit 0
