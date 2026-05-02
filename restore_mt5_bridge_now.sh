#!/bin/bash
# Restore MT5 bridge freshness after receiving a fresh MT5 export CSV.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INCOMING_FILE="$ROOT_DIR/market-causality-lab/data/live/mt5/incoming/XAUUSD_feed_latest.csv"
DATA_DIR="$ROOT_DIR/market-causality-lab/data"
API_BASE="${MT5_BRIDGE_API_BASE:-http://127.0.0.1:8000}"
PY_BIN="$ROOT_DIR/.venv/bin/python3"
SRC_FILE="${1:-}"

if [[ ! -x "$PY_BIN" ]]; then
  echo "ERROR: python not found at $PY_BIN"
  exit 2
fi

if [[ -n "$SRC_FILE" ]]; then
  if [[ ! -f "$SRC_FILE" ]]; then
    echo "ERROR: source file not found: $SRC_FILE"
    exit 2
  fi
  cp -f "$SRC_FILE" "$INCOMING_FILE"
  chmod 664 "$INCOMING_FILE" 2>/dev/null || true
  echo "Copied source -> incoming: $SRC_FILE"
else
  echo "Using existing incoming file: $INCOMING_FILE"
fi

echo "--- incoming tail ---"
tail -n 3 "$INCOMING_FILE" || true

echo "--- force bridge conversion now ---"
"$PY_BIN" "$ROOT_DIR/tools/mt5_bridge_to_mcl.py" \
  --input "$INCOMING_FILE" \
  --persist-history \
  --data-dir "$DATA_DIR"

echo "--- bridge status ---"
curl -s --max-time 12 "$API_BASE/market_causality/mt5_bridge_status?symbol=XAUUSD&timeframe=5m" | "$PY_BIN" -c "import json,sys; d=json.load(sys.stdin); b=d.get('bridge_latest') or {}; print('bridge_ready:', d.get('bridge_ready')); print('bridge_source:', b.get('source')); print('bridge_latest_ts:', b.get('last_ts')); print('bridge_age_s:', d.get('bridge_latest_age_seconds')); print('bridge_fresh:', d.get('bridge_fresh')); print('threshold_s:', d.get('bridge_fresh_threshold_seconds')); print('message:', d.get('message'))"

echo "--- chart status ---"
curl -s --max-time 20 "$API_BASE/market_causality/chart?symbol=XAUUSD&timeframe=5m&strict_mt5=false&rows=30" | "$PY_BIN" -c "import json,sys; d=json.load(sys.stdin); print('status:', d.get('status')); print('chart_source:', d.get('chart_data_source')); print('chart_live_age_s:', d.get('chart_live_dataset_age_seconds')); print('chart_mt5_fresh:', d.get('chart_mt5_bridge_fresh')); print('latest_candle_time:', d.get('latest_candle_time'))"
