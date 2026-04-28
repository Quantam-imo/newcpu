#!/bin/bash
# Container fallback scheduler for AI retraining (no systemd, no crontab).
set -euo pipefail

WORKSPACE="${AQ_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
RUNNER="$WORKSPACE/run_ai_retrain.sh"
PID_FILE="/tmp/astroquant_ai_retrain_scheduler.pid"
LOG_FILE="/tmp/astroquant_ai_retrain_scheduler.log"
INTERVAL_SEC="${AQ_AI_RETRAIN_INTERVAL_SEC:-21600}"  # 6h default

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Scheduler already running (PID: $old_pid)"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

nohup bash -c '
  set -euo pipefail
  echo $$ > "'$PID_FILE'"
  trap "rm -f \"'$PID_FILE'\"" EXIT
  echo "[$(date "+%Y-%m-%d %H:%M:%S")] AI retrain scheduler started" >> "'$LOG_FILE'"
  while true; do
    echo "[$(date "+%Y-%m-%d %H:%M:%S")] Triggering run_ai_retrain.sh" >> "'$LOG_FILE'"
    AQ_WORKSPACE="'$WORKSPACE'" /bin/bash "'$RUNNER'" >> "'$LOG_FILE'" 2>&1 || true
    echo "[$(date "+%Y-%m-%d %H:%M:%S")] Sleeping '$INTERVAL_SEC' sec" >> "'$LOG_FILE'"
    sleep "'$INTERVAL_SEC'"
  done
' >/dev/null 2>&1 &

sleep 1
if [[ -f "$PID_FILE" ]]; then
  echo "Scheduler started (PID: $(cat "$PID_FILE"))"
  echo "Log: $LOG_FILE"
else
  echo "ERROR: scheduler failed to start"
  exit 1
fi
