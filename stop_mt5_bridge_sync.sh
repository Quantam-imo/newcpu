#!/bin/bash
# Stop container fallback MT5 bridge sync daemon.
set -euo pipefail

PID_FILE="/tmp/astroquant_mt5_bridge_sync.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "MT5 bridge sync is not running (no PID file)."
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid" || true
  sleep 1
fi

rm -f "$PID_FILE"
echo "MT5 bridge sync stopped."
