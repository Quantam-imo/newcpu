#!/bin/bash
# Configure cron fallback for periodic AstroQuant AI retraining.
# Use when systemd timers are unavailable (common in dev containers).

set -euo pipefail

WORKSPACE="${AQ_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
RUNNER="$WORKSPACE/run_ai_retrain.sh"
CRON_EXPR="17 */6 * * *"
CRON_LINE="$CRON_EXPR AQ_WORKSPACE=$WORKSPACE /bin/bash $RUNNER >/tmp/astroquant_ai_retrain_cron.log 2>&1"

if [[ ! -x "$RUNNER" ]]; then
  echo "ERROR: runner not executable: $RUNNER"
  exit 1
fi

TMP_CRON="/tmp/astroquant_cron.$$"
crontab -l 2>/dev/null | grep -v "run_ai_retrain.sh" > "$TMP_CRON" || true
printf '%s\n' "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Installed cron schedule: $CRON_EXPR"
echo "Runner: $RUNNER"
echo "Log: /tmp/astroquant_ai_retrain_cron.log"
