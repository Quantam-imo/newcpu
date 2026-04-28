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
AI_HEALTH_CHECK="$WORKSPACE/check_ai_retrain_health.sh"
MT5_STATUS_CHECK="$WORKSPACE/check_mt5_bridge_freshness.sh"
MT5_START_SYNC="$WORKSPACE/start_mt5_bridge_sync.sh"
MT5_STOP_SYNC="$WORKSPACE/stop_mt5_bridge_sync.sh"

mkdir -p "$LOG_DIR"

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S UTC')" "$*" >> "$LOG_FILE"
}

restart_mt5_bridge() {
  local reason="$1"
  log "mt5 bridge restart requested: ${reason}"
  if [ -x "$MT5_STOP_SYNC" ]; then
    AQ_WORKSPACE="$WORKSPACE" /bin/bash "$MT5_STOP_SYNC" >> "$LOG_FILE" 2>&1 || true
  fi
  sleep 1
  if [ -x "$MT5_START_SYNC" ]; then
    AQ_WORKSPACE="$WORKSPACE" /bin/bash "$MT5_START_SYNC" >> "$LOG_FILE" 2>&1 || true
  fi
  if [ -x "$MT5_STATUS_CHECK" ]; then
    if AQ_WORKSPACE="$WORKSPACE" /bin/bash "$MT5_STATUS_CHECK" >> "$LOG_FILE" 2>&1; then
      log "mt5 bridge recovery success"
      FORCE_ALERT=1 bash "$WORKSPACE/send_telegram_alert.sh" mt5-bridge-recovered >> "$LOG_FILE" 2>&1 || true
      return 0
    fi
  fi
  log "mt5 bridge recovery incomplete"
  FORCE_ALERT=1 bash "$WORKSPACE/send_telegram_alert.sh" mt5-bridge-recovery-failed >> "$LOG_FILE" 2>&1 || true
  return 1
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  log "watchdog skipped: lock busy"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" >/dev/null 2>&1 || true' EXIT

need_recover=0

# Service patterns and expected singleton counts.
patterns=(
  "python .*start_astroquant.py|/start_astroquant.py"
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

# AI retrain freshness check (alert-only, does not trigger full stack restart).
if [ -x "$AI_HEALTH_CHECK" ]; then
  if ! AQ_WORKSPACE="$WORKSPACE" /bin/bash "$AI_HEALTH_CHECK" >/tmp/astroquant_ai_retrain_health.out 2>&1; then
    _msg="$(cat /tmp/astroquant_ai_retrain_health.out 2>/dev/null || echo 'AI retrain health stale')"
    log "ai retrain health warning: ${_msg}"
    FORCE_ALERT=1 bash "$WORKSPACE/send_telegram_alert.sh" ai-retrain-stale >> "$LOG_FILE" 2>&1 || true
  fi
fi

# MT5 bridge freshness check (targeted recovery only).
if [ -x "$MT5_STATUS_CHECK" ]; then
  if ! AQ_WORKSPACE="$WORKSPACE" /bin/bash "$MT5_STATUS_CHECK" >/tmp/astroquant_mt5_bridge_health.out 2>&1; then
    _mt5_msg="$(cat /tmp/astroquant_mt5_bridge_health.out 2>/dev/null || echo 'MT5 bridge stale/unhealthy')"
    log "mt5 bridge health warning: ${_mt5_msg}"
    restart_mt5_bridge "freshness check failed" || true
  fi
fi

if [ "$need_recover" -eq 0 ]; then
  log "watchdog ok: no recovery required"
  exit 0
fi

log "watchdog recovery starting"
pkill -f "start_24h_fullstack.sh" 2>/dev/null || true
pkill -f "python .*start_astroquant.py|/start_astroquant.py" 2>/dev/null || true
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
