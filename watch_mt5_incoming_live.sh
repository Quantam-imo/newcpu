#!/bin/bash
# Live monitor for MT5 incoming file freshness and bridge status.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INCOMING_FILE="${MT5_INCOMING_FILE:-$ROOT_DIR/market-causality-lab/data/live/mt5/incoming/XAUUSD_feed_latest.csv}"
API_BASE="${MT5_BRIDGE_API_BASE:-http://127.0.0.1:8000}"
SYMBOL="${MT5_BRIDGE_SYMBOL:-XAUUSD}"
TIMEFRAME="${MT5_BRIDGE_TIMEFRAME:-5m}"
INTERVAL_SEC="${MT5_WATCH_INTERVAL_SEC:-5}"
MAX_LAG_SEC="${MT5_WATCH_MAX_LAG_SEC:-900}"
ONCE="${1:-}"

if ! [[ "$INTERVAL_SEC" =~ ^[0-9]+$ ]] || [[ "$INTERVAL_SEC" -lt 1 ]]; then
  echo "Invalid MT5_WATCH_INTERVAL_SEC=$INTERVAL_SEC (must be integer >= 1)"
  exit 2
fi

echo "Monitoring MT5 feed and bridge freshness"
echo "incoming_file=$INCOMING_FILE"
echo "api_base=$API_BASE symbol=$SYMBOL timeframe=$TIMEFRAME interval_sec=$INTERVAL_SEC max_lag_sec=$MAX_LAG_SEC"
echo "Press Ctrl+C to stop"
echo

while true; do
  now_epoch="$(date +%s)"
  now_utc="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"

  incoming_exists="false"
  incoming_age="NA"
  incoming_mtime="NA"
  incoming_state="MISSING"

  if [[ -f "$INCOMING_FILE" ]]; then
    incoming_exists="true"
    mtime_epoch="$(stat -c %Y "$INCOMING_FILE")"
    incoming_age="$((now_epoch - mtime_epoch))"
    incoming_mtime="$(date -u -d "@$mtime_epoch" '+%Y-%m-%d %H:%M:%S UTC')"
    if [[ "$incoming_age" -le "$MAX_LAG_SEC" ]]; then
      incoming_state="FRESH"
    else
      incoming_state="STALE"
    fi
  fi

  api_state="DOWN"
  bridge_fresh="NA"
  bridge_age="NA"
  bridge_latest_ts="NA"
  bridge_latest_utc="NA"
  bridge_source="NA"

  api_json="$(curl -s --max-time 8 "$API_BASE/market_causality/mt5_bridge_status?symbol=$SYMBOL&timeframe=$TIMEFRAME" || true)"
  if [[ -n "$api_json" ]]; then
    parsed="$(python3 - <<'PY' "$api_json" "$now_epoch"
import json,sys,datetime
raw=sys.argv[1]
now=int(sys.argv[2])
try:
    d=json.loads(raw)
    latest=(d.get('bridge_latest') or {})
    ts=latest.get('last_ts')
    age=d.get('bridge_latest_age_seconds')
    fresh=d.get('bridge_fresh')
    src=latest.get('source') or 'NA'
    if isinstance(ts,(int,float)):
        ts_i=int(ts)
        ts_s=str(ts_i)
        ts_utc=datetime.datetime.fromtimestamp(ts_i, datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    else:
        ts_s='NA'
        ts_utc='NA'
    print('OK')
    print(str(fresh))
    print(str(age if age is not None else 'NA'))
    print(ts_s)
    print(ts_utc)
    print(src)
except Exception:
    print('DOWN')
    print('NA')
    print('NA')
    print('NA')
    print('NA')
    print('NA')
PY
)"
    api_state="$(echo "$parsed" | sed -n '1p')"
    bridge_fresh="$(echo "$parsed" | sed -n '2p')"
    bridge_age="$(echo "$parsed" | sed -n '3p')"
    bridge_latest_ts="$(echo "$parsed" | sed -n '4p')"
    bridge_latest_utc="$(echo "$parsed" | sed -n '5p')"
    bridge_source="$(echo "$parsed" | sed -n '6p')"
  fi

  overall="OK"
  if [[ "$incoming_state" != "FRESH" ]]; then
    overall="ATTN"
  fi
  if [[ "$bridge_fresh" != "True" ]]; then
    overall="ATTN"
  fi
  if [[ "$api_state" != "OK" ]]; then
    overall="ATTN"
  fi

  echo "[$now_utc] overall=$overall | incoming_exists=$incoming_exists incoming_state=$incoming_state incoming_age_s=$incoming_age incoming_mtime='$incoming_mtime' | bridge_api=$api_state bridge_fresh=$bridge_fresh bridge_age_s=$bridge_age bridge_source=$bridge_source bridge_last='$bridge_latest_utc'"

  if [[ "$ONCE" == "--once" ]]; then
    exit 0
  fi
  sleep "$INTERVAL_SEC"
done
