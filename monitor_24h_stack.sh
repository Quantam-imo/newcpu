#!/bin/bash
# Monitor AstroQuant 24/7 stack status and performance
# Usage: ./monitor_24h_stack.sh [interval=10]

INTERVAL="${1:-10}"
LOG_DIR="data/logs"

clear

echo "========================================="
echo "AstroQuant 24/7 Stack Monitor"
echo "========================================="
echo "Refresh: ${INTERVAL}s | Press Ctrl+C to exit"
echo ""

while true; do
  clear
  
  echo "========================================="
  echo "TIME: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "========================================="
  echo ""
  
  # Redis
  echo "┌─ Redis"
  if redis-cli ping > /dev/null 2>&1; then
    MEM=$(redis-cli info memory | grep used_memory_human | cut -d: -f2)
    KEYS=$(redis-cli dbsize | grep keys | cut -d: -f2)
    echo "  ✓ RUNNING | Memory: $MEM | Keys: $KEYS"
  else
    echo "  ✗ DOWN"
  fi
  echo ""
  
  # Celery
  echo "┌─ Celery Worker"
  if pgrep -f "celery.*worker" > /dev/null; then
    CELERY_PROCS=$(pgrep -f "celery.*worker" | wc -l)
    echo "  ✓ RUNNING | Processes: $CELERY_PROCS"
  else
    echo "  ✗ DOWN"
  fi
  echo ""
  
  # Orchestrator
  echo "┌─ Orchestrator"
  if [ -f "$LOG_DIR/orchestrator.pid" ]; then
    PID=$(cat "$LOG_DIR/orchestrator.pid" 2>/dev/null)
    if kill -0 "$PID" 2>/dev/null; then
      echo "  ✓ RUNNING | PID: $PID"
    else
      echo "  ✗ DOWN | Last PID: $PID"
    fi
  else
    echo "  ✗ NOT STARTED"
  fi
  echo ""
  
  # Backend
  echo "┌─ FastAPI Backend"
  if curl -s http://127.0.0.1:8000/status > /dev/null 2>&1; then
    UPTIME=$(curl -s http://127.0.0.1:8000/status 2>/dev/null | grep -o '"uptime":[0-9]*' | cut -d: -f2)
    echo "  ✓ RUNNING | Port: 8000 | Uptime: ${UPTIME}s"
  else
    echo "  ✗ DOWN"
  fi
  echo ""
  
  # Chrome
  echo "┌─ Chrome Remote Debug"
  if curl -s http://127.0.0.1:9222/json/version > /dev/null 2>&1; then
    echo "  ✓ RUNNING | Port: 9222"
  else
    echo "  ✗ DOWN"
  fi
  echo ""
  
  # Cloudflare Tunnel
  echo "┌─ Cloudflare Tunnel"
  if pgrep -f "cloudflared tunnel" > /dev/null; then
    TUNNEL_URL=$(cat data/tunnel_url.txt 2>/dev/null || echo "PENDING")
    echo "  ✓ RUNNING | URL: $TUNNEL_URL"
  else
    echo "  ✗ DOWN"
  fi
  echo ""
  
  # CF Unblock
  echo "┌─ Cloudflare Unblock Monitor"
  if pgrep -f "cloudflare_unblock.py" > /dev/null; then
    echo "  ✓ RUNNING"
  else
    echo "  ✗ DOWN"
  fi
  echo ""
  
  # System Resources
  echo "┌─ System Resources"
  CPU=$(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)
  MEM=$(free | grep Mem | awk '{printf("%.1f%%", $3/$2 * 100)}')
  echo "  CPU: $CPU% | Memory: $MEM"
  echo ""
  
  # Recent Errors
  echo "┌─ Recent Errors (Last 5)"
  tail -n 5 "$LOG_DIR/fullstack.log" 2>/dev/null | grep -i "error\|fail\|critical" || echo "  ✓ No recent errors"
  echo ""
  
  echo "========================================="
  echo "Waiting ${INTERVAL}s for next refresh..."
  sleep "$INTERVAL"
done
