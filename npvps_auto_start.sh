#!/bin/bash
# NPVPS CPU Auto-Start Wrapper
# Simple, production-ready startup for 24/7 autonomous operation
# Usage: ./npvps_auto_start.sh [--no-chrome] [--no-tunnel] [--no-novpn]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${AQ_WORKSPACE:-$SCRIPT_DIR}"

cd "$WORKSPACE"

echo "========================================="
echo "AstroQuant NPVPS CPU Auto-Start"
echo "Time: $(date)"
echo "========================================="
echo ""

# Clean up old processes
echo "Cleaning up old processes..."
pkill -f "bash start_24h_fullstack.sh" 2>/dev/null || true
pkill -9 -f "redis-server|celery|uvicorn|cloudflared|chrome-remote|novpn" 2>/dev/null || true
pkill -f "$WORKSPACE/telegram_bot_daemon.py" 2>/dev/null || true
sleep 2

# Now run the full stack
echo ""
echo "Starting full stack in background..."
nohup bash start_24h_fullstack.sh "$@" > data/logs/auto_start.log 2>&1 &

FULLSTACK_PID=$!
echo $FULLSTACK_PID > /tmp/astroquant_fullstack.pid

echo ""
echo "Full stack starting (PID: $FULLSTACK_PID)"
echo "Monitor with: tail -f data/logs/fullstack.log"
echo "Or: bash monitor_24h_stack.sh"
echo ""

# Give it time to start
sleep 10

# Check if it's running
if kill -0 $FULLSTACK_PID 2>/dev/null; then
  echo "✓ Full stack is running"
  echo ""
  echo "Dashboard: http://127.0.0.1:8000/frontend/"
  echo ""
else
  echo "✗ Full stack failed to start"
  echo "Check logs: tail -50 data/logs/fullstack.log"
  exit 1
fi
