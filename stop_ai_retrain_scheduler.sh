#!/bin/bash
# Stop container fallback AI retraining scheduler.
set -euo pipefail

PID_FILE="/tmp/astroquant_ai_retrain_scheduler.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "Scheduler is not running (no PID file)."
  exit 0
fi

pid="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
  kill "$pid" || true
  sleep 1
fi

rm -f "$PID_FILE"
echo "Scheduler stopped."
