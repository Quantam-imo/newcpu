#!/bin/bash
# Status check for container fallback AI retraining scheduler.
set -euo pipefail

PID_FILE="/tmp/astroquant_ai_retrain_scheduler.pid"
LOG_FILE="/tmp/astroquant_ai_retrain_scheduler.log"
WORKSPACE="${AQ_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "RUNNING (PID: $pid)"
    if [[ -x "$WORKSPACE/check_ai_retrain_health.sh" ]]; then
      AQ_WORKSPACE="$WORKSPACE" /bin/bash "$WORKSPACE/check_ai_retrain_health.sh" || true
    fi
    echo "Recent log:"
    tail -n 20 "$LOG_FILE" 2>/dev/null || true
    exit 0
  fi
fi

echo "NOT RUNNING"
exit 1
