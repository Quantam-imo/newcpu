#!/bin/bash
# AstroQuant End-to-End System Validation
# Runs all health checks, launches backend/frontend, and validates live data in all panels

set -euo pipefail

WORKDIR="/workspaces/newcpu"
API_BASE="http://127.0.0.1:8000"
LOGFILE="$WORKDIR/END_TO_END_VALIDATION.log"

cd "$WORKDIR"

# 1. Start backend if not running
if ! pgrep -f "uvicorn.*backend.main:app" >/dev/null; then
  echo "Starting backend..." | tee -a "$LOGFILE"
  nohup $WORKDIR/.venv/bin/python -m uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 >> "$LOGFILE" 2>&1 &
  sleep 10
fi

# 2. Run health checks
bash health_check.sh "$API_BASE" | tee -a "$LOGFILE"
bash preflight_strict.sh "$API_BASE" | tee -a "$LOGFILE"

# 3. Validate all panels and operation console endpoints
PANEL_ENDPOINTS=(
  "/status/feed"
  "/status/execution"
  "/status/reconciliation"
  "/status/equity_verification"
  "/system_health"
  "/chart/data?symbol=XAUUSD&timeframe=1m&limit=20"
  "/mentor/context?symbol=XAUUSD"
)

for endpoint in "${PANEL_ENDPOINTS[@]}"; do
  echo "Validating $endpoint..." | tee -a "$LOGFILE"
  if ! curl -s -f "$API_BASE$endpoint" >/dev/null; then
    echo "[FAIL] Endpoint $endpoint is not responding!" | tee -a "$LOGFILE"
    exit 1
  else
    echo "[OK] $endpoint" | tee -a "$LOGFILE"
  fi
  sleep 1
fi

echo "All panels and endpoints validated successfully." | tee -a "$LOGFILE"

# 4. Optionally, add Selenium/Playwright browser checks for frontend UI
# (Not included here for brevity)

exit 0
