#!/bin/bash
# AstroQuant Automated Health Monitor
# Runs health_check.sh and preflight_strict.sh, sends alert if any check fails
# Add to cron or systemd timer for continuous monitoring

set -euo pipefail

WORKDIR="/workspaces/newcpu"
API_BASE="http://127.0.0.1:8000"
ALERT_EMAIL="your-alert-email@example.com"  # Set to your alert email or Slack webhook
LOGFILE="$WORKDIR/HEALTH_MONITOR.log"

cd "$WORKDIR"

run_and_alert() {
  local script="$1"
  local label="$2"
  local result=0
  bash "$script" "$API_BASE" > "$LOGFILE" 2>&1 || result=$?
  if [[ $result -ne 0 ]]; then
    echo "[$(date)] $label FAILED. See $LOGFILE" | tee -a "$LOGFILE"
    # Send alert (email example, replace with Slack/Telegram if needed)
    if command -v mail >/dev/null 2>&1; then
      mail -s "[ALERT] AstroQuant $label FAILED" "$ALERT_EMAIL" < "$LOGFILE"
    fi
    # Optionally, add curl command for Slack/Telegram webhook here
  else
    echo "[$(date)] $label PASSED." | tee -a "$LOGFILE"
  fi
}

run_and_alert health_check.sh "Health Check"
run_and_alert preflight_strict.sh "Preflight Strict"

# Optionally, add more checks or custom logic here
