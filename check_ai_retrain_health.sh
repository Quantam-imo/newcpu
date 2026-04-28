#!/bin/bash
# Check AstroQuant AI retrain freshness and scheduler health.

set -euo pipefail

WORKSPACE="${AQ_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
LOG_DIR="$WORKSPACE/data/logs"
SUCCESS_MARKER="$LOG_DIR/ai_retrain_last_success.json"
SCHED_PID_FILE="/tmp/astroquant_ai_retrain_scheduler.pid"

# Default healthy if latest retrain started within 7 hours.
MAX_AGE_SEC="${AQ_AI_RETRAIN_MAX_AGE_SEC:-25200}"

now_epoch="$(date +%s)"

status_ok=1
messages=()

training_active=0
if pgrep -f "bash train_all_complete.sh|python train_ai_models.py|python scripts/generate_gann_moon_aspects.py|python scripts/generate_gann_cycles_nodes.py" >/dev/null 2>&1; then
  training_active=1
  messages+=("training=active")
else
  messages+=("training=idle")
fi

# Scheduler process check
if [[ -f "$SCHED_PID_FILE" ]]; then
  sched_pid="$(cat "$SCHED_PID_FILE" 2>/dev/null || true)"
  if [[ -n "$sched_pid" ]] && kill -0 "$sched_pid" 2>/dev/null; then
    messages+=("scheduler=running(pid:$sched_pid)")
  else
    messages+=("scheduler=stale_pid")
    status_ok=0
  fi
else
  messages+=("scheduler=missing")
  status_ok=0
fi

# Full-cycle success marker freshness (includes 1m completion confirmation).
if [[ ! -f "$SUCCESS_MARKER" ]]; then
  messages+=("success_marker=missing")
  if [[ "$training_active" -eq 0 ]]; then
    status_ok=0
  fi
else
  marker_contains_1m="$(grep -o '"contains_1m"[[:space:]]*:[[:space:]]*[^,}]*' "$SUCCESS_MARKER" | awk -F: '{gsub(/[[:space:]]/,"",$2); print tolower($2)}' | head -1 || true)"
  marker_log_file="$(grep -o '"log_file"[[:space:]]*:[[:space:]]*"[^"]*"' "$SUCCESS_MARKER" | head -1 | cut -d '"' -f4 || true)"

  if [[ "$marker_contains_1m" != "true" ]]; then
    messages+=("marker_1m=false")
    status_ok=0
  else
    messages+=("marker_1m=true")
  fi

  if [[ -n "$marker_log_file" && -f "$marker_log_file" ]]; then
    mtime_epoch="$(stat -c %Y "$marker_log_file" 2>/dev/null || echo 0)"
    age_sec=$((now_epoch - mtime_epoch))
    messages+=("latest_log=$(basename "$marker_log_file")")
    messages+=("age_sec=$age_sec")
    if (( age_sec > MAX_AGE_SEC )) && [[ "$training_active" -eq 0 ]]; then
      messages+=("freshness=stale")
      status_ok=0
    else
      messages+=("freshness=ok")
    fi
  else
    messages+=("marker_log_missing")
    status_ok=0
  fi
fi

if [[ "$status_ok" -eq 1 ]]; then
  echo "AI_RETRAIN_HEALTH=OK ${messages[*]}"
  exit 0
fi

echo "AI_RETRAIN_HEALTH=STALE ${messages[*]}"
exit 1
