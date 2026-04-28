#!/bin/bash
# Container fallback scheduler for MT5 bridge sync daemon.
set -euo pipefail

WORKSPACE="${AQ_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
RUNNER="$WORKSPACE/tools/mt5_bridge_sync_daemon.py"
PID_FILE="/tmp/astroquant_mt5_bridge_sync.pid"
LOG_FILE="/tmp/astroquant_mt5_bridge_sync.log"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "MT5 bridge sync already running (PID: $old_pid)"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

nohup bash -c '
  set -euo pipefail
  echo $$ > "'$PID_FILE'"
  trap "rm -f \"'$PID_FILE'\"" EXIT
  echo "[$(date "+%Y-%m-%d %H:%M:%S")] MT5 bridge sync started" >> "'$LOG_FILE'"
  export AQ_WORKSPACE="'$WORKSPACE'"
  export PYTHONPATH="'$WORKSPACE'/tools"
  export MT5_BRIDGE_SOURCE_DIR="${MT5_BRIDGE_SOURCE_DIR:-'$WORKSPACE'/market-causality-lab/data/live/mt5/incoming}"
  export MT5_BRIDGE_OUT_DIR="${MT5_BRIDGE_OUT_DIR:-'$WORKSPACE'/market-causality-lab/data/live/mt5}"
  export MT5_BRIDGE_DATA_DIR="${MT5_BRIDGE_DATA_DIR:-'$WORKSPACE'/market-causality-lab/data}"
  export MT5_BRIDGE_TIMEFRAME="${MT5_BRIDGE_TIMEFRAME:-5m}"
  export MT5_BRIDGE_PERSIST_HISTORY="1"
  export MT5_BRIDGE_POLL_SEC="${MT5_BRIDGE_POLL_SEC:-1}"
  export MT5_BRIDGE_STABLE_POLLS="${MT5_BRIDGE_STABLE_POLLS:-1}"
  # 5m MT5 feed cadence: alert when lag is meaningfully stale, not every poll.
  export MT5_BRIDGE_LAG_ALERT_SEC="${MT5_BRIDGE_LAG_ALERT_SEC:-900}"
  "'$WORKSPACE'/.venv/bin/python3" "'$RUNNER'" >> "'$LOG_FILE'" 2>&1
' >/dev/null 2>&1 &

sleep 1
if [[ -f "$PID_FILE" ]]; then
  echo "MT5 bridge sync started (PID: $(cat "$PID_FILE"))"
  echo "Log: $LOG_FILE"
else
  echo "ERROR: MT5 bridge sync failed to start"
  exit 1
fi
