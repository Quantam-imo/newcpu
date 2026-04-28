#!/bin/bash
# Stop all AstroQuant services safely
# Usage: ./stop_24h_fullstack.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"
TELEGRAM_PATTERN="$WORKSPACE/telegram_bot_daemon.py"

echo "========================================="
echo "Stopping AstroQuant Full Stack..."
echo "========================================="
echo ""

# Kill main processes
echo "Stopping processes..."
pkill -f "bash start_24h_fullstack.sh" || echo "Fullstack supervisor not running"
pkill -f "npvps_auto_start.sh" || echo "Auto-start wrapper not running"
pkill -f "celery -A astroquant" || echo "Celery not running"
pkill -f "python .*start_astroquant.py|/start_astroquant.py" || echo "Orchestrator not running"
pkill -f "uvicorn.*main:app" || echo "Backend not running"
pkill -f "cloudflared tunnel" || echo "Tunnel not running"
pkill -f "python cloudflare_unblock.py" || echo "CF unblock not running"
pkill -f "$TELEGRAM_PATTERN" || echo "Telegram daemon not running"
pkill -f "chrome-remote-debug" 2>/dev/null || echo "Chrome not running"
pkill -f "tools/mt5_bridge_sync_daemon.py" 2>/dev/null || echo "MT5 bridge sync not running"
if [ -x "$WORKSPACE/stop_mt5_bridge_sync.sh" ]; then
  bash "$WORKSPACE/stop_mt5_bridge_sync.sh" >/dev/null 2>&1 || true
fi

# Stop Redis
redis-cli shutdown 2>/dev/null || echo "Redis not running"

echo ""
echo "Waiting for processes to terminate..."
sleep 2

# Verify all stopped
remaining=$(pgrep -f "start_24h_fullstack.sh|npvps_auto_start.sh|celery|python start_astroquant|uvicorn|cloudflared|$TELEGRAM_PATTERN|chrome" | wc -l)

if [ "$remaining" -eq 0 ]; then
  echo "✓ All AstroQuant services stopped"
else
  echo "⚠ $remaining processes still running:"
  pgrep -f "start_24h_fullstack.sh|npvps_auto_start.sh|celery|python start_astroquant|uvicorn|cloudflared|$TELEGRAM_PATTERN|chrome" || true
fi

echo "========================================="
