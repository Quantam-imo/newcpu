#!/bin/bash
# Strict health check for MT5 feed freshness before allowing operational startup.
# Fails if incoming MT5 feed is stale or missing, preventing silent data gaps.
set -euo pipefail

WORKSPACE="${AQ_WORKSPACE:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
INCOMING_DIR="$WORKSPACE/market-causality-lab/data/live/mt5/incoming"
MAX_LAG_SEC="${MT5_HEALTH_MAX_LAG_SEC:-86400}"  # Allow up to 24h (operational grace period for manual MT5 exports)
REQUIRED_ROWS="${MT5_HEALTH_MIN_ROWS:-50}"
WARN_LAG_SEC="${MT5_HEALTH_WARN_LAG_SEC:-3600}"  # Warn if feed older than 1 hour

echo "=== MT5 Feed Health Check ==="
echo "Incoming dir: $INCOMING_DIR"
echo "Max lag: ${MAX_LAG_SEC}s"
echo "Min rows: $REQUIRED_ROWS"
echo ""

if [[ ! -d "$INCOMING_DIR" ]]; then
  echo "ERROR: Incoming feed directory does not exist: $INCOMING_DIR"
  exit 1
fi

newest_file=$(find "$INCOMING_DIR" -maxdepth 1 -name "XAUUSD*.csv" -type f -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-)

if [[ -z "$newest_file" ]]; then
  echo "ERROR: No MT5 feed file found in $INCOMING_DIR"
  exit 1
fi

file_mtime=$(stat -c '%Y' "$newest_file")
now_sec=$(date +%s)
lag_sec=$((now_sec - file_mtime))

row_count=$(wc -l < "$newest_file" 2>/dev/null | awk '{print $1-1}')  # Subtract header

echo "Latest feed: $(basename "$newest_file")"
echo "File age: ${lag_sec}s ($(($lag_sec / 3600))h $(($lag_sec % 3600 / 60))m)"
echo "Row count: $row_count"
echo ""

if [[ $lag_sec -gt $WARN_LAG_SEC ]]; then
  echo "⚠️  WARNING: Feed is older than 1h — ensure MetaEditor exports are running"
fi

if [[ $lag_sec -gt $MAX_LAG_SEC ]]; then
  echo "❌ FAIL: Feed is too stale (${lag_sec}s > ${MAX_LAG_SEC}s)"
  exit 1
fi

if [[ $row_count -lt $REQUIRED_ROWS ]]; then
  echo "❌ FAIL: Feed has too few rows ($row_count < $REQUIRED_ROWS)"
  exit 1
fi

if [[ $lag_sec -gt $WARN_LAG_SEC ]]; then
  echo "✅ PASS: MT5 feed is present but aging (within operational tolerance)"
else
  echo "✅ PASS: MT5 feed is fresh and well-populated"
fi
exit 0
