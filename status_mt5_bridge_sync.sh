#!/bin/bash
# Status check for container fallback MT5 bridge sync daemon.
set -euo pipefail

PID_FILE="/tmp/astroquant_mt5_bridge_sync.pid"
LOG_FILE="/tmp/astroquant_mt5_bridge_sync.log"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "RUNNING (PID: $pid)"
    if [[ -x "./check_mt5_bridge_freshness.sh" ]]; then
      ./check_mt5_bridge_freshness.sh || true
    fi
    echo "Recent log:"
    tail -n 20 "$LOG_FILE" 2>/dev/null || true
    exit 0
  fi
fi

echo "NOT RUNNING"
exit 1
