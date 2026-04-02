#!/bin/bash
# Auto-recovery watchdog for AstroQuant core stack.
# Runs safely as a periodic timer and only triggers bootstrap when needed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
LOG_DIR="$WORKSPACE/data/logs"
LOG_FILE="$LOG_DIR/watchdog.log"
LOCK_DIR="/tmp/astroquant_watchdog.lock"
BOOTSTRAP="$WORKSPACE/non_systemd_autostart_bootstrap.sh"

mkdir -p "$LOG_DIR"

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')" "$*" >> "$LOG_FILE"
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "watchdog skipped: lock busy"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" >/dev/null 2>&1 || true' EXIT

need_recover=0

# Service patterns and expected singleton counts.
patterns=(
  "start_astroquant.py"
  "uvicorn.*astroquant.backend.main:app"
  "celery.*astroquant.backend.tasks.celery_worker"
  "telegram_bot_daemon.py"
  "cloudflared tunnel --url http://localhost:8000"
)

for pattern in "${patterns[@]}"; do
  pids="$(pgrep -f "$pattern" || true)"
  count="$(printf '%s\n' "$pids" | sed '/^$/d' | wc -l)"
  if [ "$count" -eq 0 ]; then
    log "missing process: $pattern"
    need_recover=1
  elif [ "$count" -gt 1 ]; then
    log "duplicate process count=$count: $pattern"
    need_recover=1
  fi
done

if ! curl -s -m 5 http://127.0.0.1:8000/status >/dev/null 2>&1; then
  log "backend status check failed"
  need_recover=1
fi

if [ "$need_recover" -eq 0 ]; then
  log "watchdog ok: no recovery required"
  exit 0
fi

log "watchdog recovery starting"
pkill -f "start_24h_fullstack.sh" 2>/dev/null || true
pkill -f "start_astroquant.py" 2>/dev/null || true
pkill -f "uvicorn.*astroquant.backend.main:app" 2>/dev/null || true
pkill -f "celery.*astroquant.backend.tasks.celery_worker" 2>/dev/null || true
pkill -f "telegram_bot_daemon.py" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://localhost:8000" 2>/dev/null || true
pkill -f "cloudflared tunnel --url http://localhost:6080" 2>/dev/null || true

sleep 2
AQ_WORKSPACE="$WORKSPACE" /bin/bash "$BOOTSTRAP" >> "$LOG_FILE" 2>&1 || true

if curl -s -m 10 http://127.0.0.1:8000/status >/dev/null 2>&1; then
  log "watchdog recovery success"
  bash "$WORKSPACE/send_telegram_alert.sh" watchdog-recovered >> "$LOG_FILE" 2>&1 || true
else
  log "watchdog recovery incomplete"
  bash "$WORKSPACE/send_telegram_alert.sh" watchdog-recovery-failed >> "$LOG_FILE" 2>&1 || true
fi
