#!/bin/bash
# Verify reboot recovery layers for AstroQuant.
#
# Usage:
#   bash verify_reboot_recovery.sh
#   bash verify_reboot_recovery.sh --chaos-test
#
# --chaos-test: stops stack processes, triggers bootstrap, waits for backend recovery.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
DATA_DIR="$WORKSPACE/data"
LOG_DIR="$DATA_DIR/logs"
BOOTSTRAP="$WORKSPACE/non_systemd_autostart_bootstrap.sh"
AUTOSTART_SETUP="$WORKSPACE/enable_boot_autostart.sh"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

ok() { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERR]${NC} $*"; }
step() { echo -e "${BLUE}-->${NC} $*"; }

pass_count=0
warn_count=0
fail_count=0

record_ok() {
  pass_count=$((pass_count + 1))
  ok "$*"
}

record_warn() {
  warn_count=$((warn_count + 1))
  warn "$*"
}

record_fail() {
  fail_count=$((fail_count + 1))
  err "$*"
}

check_file_exec() {
  local path="$1"
  local label="$2"
  if [ -x "$path" ]; then
    record_ok "$label is executable ($path)"
  elif [ -f "$path" ]; then
    record_warn "$label exists but is not executable ($path)"
  else
    record_fail "$label missing ($path)"
  fi
}

check_systemd_units() {
  step "Checking systemd unit provisioning"
  local unit_file="/etc/systemd/system/astroquant_tradingbot.service"
  local unit_link="/etc/systemd/system/multi-user.target.wants/astroquant_tradingbot.service"

  if [ -f "$unit_file" ]; then
    record_ok "systemd unit exists ($unit_file)"
  else
    record_warn "systemd unit file not found ($unit_file)"
  fi

  if [ -L "$unit_link" ] || [ -f "$unit_link" ]; then
    record_ok "systemd enable link exists ($unit_link)"
  else
    record_warn "systemd enable link missing ($unit_link)"
  fi

  if [ "$(ps -p 1 -o comm= 2>/dev/null || true)" = "systemd" ]; then
    if systemctl is-enabled astroquant_tradingbot.service >/dev/null 2>&1; then
      record_ok "astroquant_tradingbot.service is enabled"
    else
      record_warn "astroquant_tradingbot.service is not enabled"
    fi
  else
    record_warn "runtime PID1 is not systemd (expected in containers/codespaces)"
  fi
}

check_cron_reboot() {
  step "Checking cron reboot fallback"
  if ! command -v crontab >/dev/null 2>&1; then
    record_warn "crontab command unavailable"
    return
  fi

  if crontab -l 2>/dev/null | grep -q "astroquant reboot bootstrap"; then
    record_ok "cron @reboot bootstrap entry present"
  else
    record_warn "cron @reboot bootstrap entry missing"
  fi
}

check_shell_hooks() {
  step "Checking shell fallback hooks"
  local b_hook="$(grep -c "astroquant non-systemd autostart" "$HOME/.bashrc" 2>/dev/null || true)"
  local p_hook="$(grep -c "astroquant non-systemd autostart" "$HOME/.profile" 2>/dev/null || true)"

  if [ "$b_hook" -gt 0 ]; then
    record_ok "bashrc fallback hook present"
  else
    record_warn "bashrc fallback hook missing"
  fi

  if [ "$p_hook" -gt 0 ]; then
    record_ok "profile fallback hook present"
  else
    record_warn "profile fallback hook missing"
  fi
}

check_runtime_health() {
  step "Checking current runtime health"
  if curl -s -m 5 http://127.0.0.1:8000/status >/dev/null 2>&1; then
    record_ok "backend status endpoint responds"
  else
    record_warn "backend status endpoint not responding"
  fi

  if pgrep -f "cloudflared tunnel --url http://localhost:8000" >/dev/null 2>&1; then
    record_ok "app cloudflare tunnel process running"
  else
    record_warn "app cloudflare tunnel process not running"
  fi

  if pgrep -f "telegram_bot_daemon.py" >/dev/null 2>&1; then
    record_ok "telegram daemon process running"
  else
    record_warn "telegram daemon process not running"
  fi

  check_singleton "start_astroquant.py" "orchestrator"
  check_singleton "uvicorn.*astroquant.backend.main:app" "backend"
  check_singleton "celery.*astroquant.backend.tasks.celery_worker" "celery"
  check_singleton "telegram_bot_daemon.py" "telegram daemon"
  check_singleton "cloudflared tunnel --url http://localhost:8000" "app tunnel"
}

check_singleton() {
  local pattern="$1"
  local label="$2"
  local pids
  local count
  pids="$(pgrep -f "$pattern" || true)"
  count="$(printf "%s\n" "$pids" | sed '/^$/d' | wc -l)"

  if [ "$count" -eq 1 ]; then
    record_ok "$label singleton count=1"
  elif [ "$count" -eq 0 ]; then
    record_warn "$label process not running"
  else
    record_fail "$label duplicate instances detected (count=$count)"
  fi
}

check_required_env() {
  step "Checking required environment keys"
  local env_file="$WORKSPACE/.env"
  if [ ! -f "$env_file" ]; then
    record_warn ".env file missing ($env_file)"
    return
  fi

  local required=(
    DATABENTO_API_KEY
    TELEGRAM_ALERT_ENABLED
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID
    TELEGRAM_SIGNAL_SYMBOLS
    TELEGRAM_DAY_BOUNDARY_REPORTS_ENABLED
    TELEGRAM_DAY_START_UTC
    TELEGRAM_DAY_END_UTC
  )

  local missing=0
  for key in "${required[@]}"; do
    if grep -Eq "^${key}=.+" "$env_file"; then
      record_ok "env key present: $key"
    else
      record_warn "env key missing/empty: $key"
      missing=$((missing + 1))
    fi
  done

  if [ "$missing" -eq 0 ]; then
    record_ok "required environment keys complete"
  fi
}

check_watchdog_provisioning() {
  step "Checking watchdog provisioning"
  local unit_file="/etc/systemd/system/astroquant_watchdog.service"
  local timer_file="/etc/systemd/system/astroquant_watchdog.timer"
  local timer_link="/etc/systemd/system/timers.target.wants/astroquant_watchdog.timer"

  if [ -f "$unit_file" ]; then
    record_ok "watchdog unit exists ($unit_file)"
  else
    record_warn "watchdog unit missing ($unit_file)"
  fi

  if [ -f "$timer_file" ]; then
    record_ok "watchdog timer exists ($timer_file)"
  else
    record_warn "watchdog timer missing ($timer_file)"
  fi

  if [ -L "$timer_link" ] || [ -f "$timer_link" ]; then
    record_ok "watchdog timer enabled link exists ($timer_link)"
  else
    record_warn "watchdog timer enable link missing ($timer_link)"
  fi
}

chaos_test() {
  step "Starting controlled chaos recovery test"
  mkdir -p "$LOG_DIR"

  # Stop stack processes only (do not touch git/workspace content).
  pkill -f "start_24h_fullstack.sh" 2>/dev/null || true
  pkill -f "uvicorn.*astroquant.backend.main:app" 2>/dev/null || true
  pkill -f "celery.*astroquant.backend.tasks.celery_worker" 2>/dev/null || true
  pkill -f "telegram_bot_daemon.py" 2>/dev/null || true
  pkill -f "cloudflared tunnel --url http://localhost:8000" 2>/dev/null || true
  pkill -f "cloudflared tunnel --url http://localhost:6080" 2>/dev/null || true
  pkill -f "start_novpn_connector.sh" 2>/dev/null || true
  sleep 2

  step "Triggering bootstrap"
  AQ_WORKSPACE="$WORKSPACE" bash "$BOOTSTRAP" || true

  step "Waiting up to 180s for backend recovery"
  local waited=0
  while [ "$waited" -lt 180 ]; do
    if curl -s -m 5 http://127.0.0.1:8000/status >/dev/null 2>&1; then
      record_ok "chaos test recovery succeeded in ${waited}s"
      return 0
    fi

    # Progress indicator to distinguish hard-fail from slow cold start.
    if pgrep -f "uvicorn.*astroquant.backend.main:app|start_24h_fullstack.sh|python start_astroquant.py" >/dev/null 2>&1; then
      step "Recovery in progress (${waited}s): core startup processes detected"
    fi

    sleep 5
    waited=$((waited + 5))
  done

  record_fail "chaos test recovery failed (backend still down after 180s)"
  return 1
}

main() {
  local run_chaos=0
  if [ "${1:-}" = "--chaos-test" ]; then
    run_chaos=1
  fi

  echo ""
  echo "========================================="
  echo "AstroQuant Reboot Recovery Verification"
  echo "Workspace: $WORKSPACE"
  echo "========================================="

  check_file_exec "$AUTOSTART_SETUP" "autostart setup script"
  check_file_exec "$BOOTSTRAP" "bootstrap script"
  check_systemd_units
  check_watchdog_provisioning
  check_cron_reboot
  check_shell_hooks
  check_required_env
  check_runtime_health

  if [ "$run_chaos" -eq 1 ]; then
    chaos_test || true
  fi

  echo ""
  echo "========================================="
  echo "Summary: PASS=$pass_count WARN=$warn_count FAIL=$fail_count"
  echo "========================================="

  if [ "$fail_count" -gt 0 ]; then
    exit 1
  fi
  exit 0
}

main "$@"
