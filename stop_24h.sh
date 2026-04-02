#!/bin/bash
# ============================================================================
# AstroQuant — 24/7 Stop Script
# ============================================================================
# Gracefully stops all AstroQuant tmux sessions.
# Usage:
#   ./stop_24h.sh         # stop all sessions
#   ./stop_24h.sh --hard  # also kill Redis + stray processes
# ============================================================================

set -euo pipefail
cd "$(dirname "$0")"

HARD=false
for arg in "${@:-}"; do
  [ "$arg" = "--hard" ] && HARD=true
done

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[stop]${NC} $*"; }
warn() { echo -e "${YELLOW}[stop]${NC} $*"; }

SESSIONS=(aq-livesync aq-orchestrator aq-celery aq-backend aq-cf-unblock aq-chrome aq-redis)

for s in "${SESSIONS[@]}"; do
  if tmux has-session -t "$s" 2>/dev/null; then
    tmux kill-session -t "$s" 2>/dev/null || true
    log "Stopped: $s"
  else
    warn "Not running: $s"
  fi
done

if [ "$HARD" = true ]; then
  log "Hard stop: killing any remaining uvicorn/celery/chrome processes..."
  pkill -f "uvicorn.*astroquant" 2>/dev/null || true
  pkill -f "celery.*astroquant" 2>/dev/null || true
  pkill -f "start_astroquant.py" 2>/dev/null || true
  pkill -f "start_live_sync.py" 2>/dev/null || true
  pkill -f "cloudflare_unblock.py" 2>/dev/null || true
  pkill -f "remote-debugging-port=9222" 2>/dev/null || true
  redis-cli shutdown nosave 2>/dev/null || true
  log "Hard stop complete."
fi

log "All AstroQuant sessions stopped."
echo "  Restart with: ./start_24h.sh"
