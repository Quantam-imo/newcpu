#!/bin/bash
# Verify MT5 -> MCL pipeline freshness, propagation speed, and chart gap-fill behavior.
set -euo pipefail

API_BASE="${API_BASE:-http://127.0.0.1:8000}"
PROXY_BASE="${PROXY_BASE:-http://127.0.0.1:5000}"
SYMBOL="${SYMBOL:-XAUUSD}"
TIMEFRAMES="${TIMEFRAMES:-1m 5m 15m 30m 1h 4h 1d}"
MAX_LIVE_AGE_SEC="${MAX_LIVE_AGE_SEC:-900}"
MAX_MT5_FILE_AGE_SEC="${MAX_MT5_FILE_AGE_SEC:-900}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INCOMING_FILE="$ROOT_DIR/market-causality-lab/data/live/mt5/incoming/XAUUSD_feed_latest.csv"
MT5_5M_FILE="$ROOT_DIR/market-causality-lab/data/live/mt5/XAUUSD_5m.csv"
MT5_5M_INTRADAY_FILE="$ROOT_DIR/market-causality-lab/data/live/mt5/XAUUSD_live_5m_intraday.csv"

fail=0
warn=0

say() { printf '%s\n' "$*"; }
section() { printf '\n=== %s ===\n' "$*"; }

section "Bridge Status"
bridge_json="$(curl -sS --max-time 12 "$API_BASE/market_causality/mt5_bridge_status?symbol=$SYMBOL&timeframe=5m")"
set +e
python3 - <<'PY' "$bridge_json" "$MAX_LIVE_AGE_SEC"
import json, sys, time
payload = json.loads(sys.argv[1])
max_age = int(sys.argv[2])
best = payload.get("best_live_quote") or {}
source = str(best.get("source") or "--")
ts = best.get("ts")
now = int(time.time())
age = (now - int(ts)) if isinstance(ts, (int, float)) else None
print(f"bridge_ready: {payload.get('bridge_ready')}")
print(f"chart_ingestion_ready: {payload.get('chart_ingestion_ready')}")
print(f"best_source: {source}")
print(f"best_ts: {ts}")
print(f"best_age_sec: {age}")
if not payload.get("bridge_ready"):
    print("RESULT bridge: FAIL bridge_ready=false")
    raise SystemExit(21)
if age is None:
    print("RESULT bridge: FAIL best_live_quote.ts missing")
    raise SystemExit(22)
if age > max_age:
    print(f"RESULT bridge: FAIL stale best quote age={age}s > {max_age}s")
    raise SystemExit(23)
if not source.startswith("mt5_"):
    print(f"RESULT bridge: WARN best source is non-MT5 ({source})")
    raise SystemExit(24)
print("RESULT bridge: PASS")
PY
bridge_rc=$?
set -e
if [[ $bridge_rc -eq 24 ]]; then
  say "bridge_check: WARN non-MT5 source active"
  warn=$((warn + 1))
elif [[ $bridge_rc -ne 0 ]]; then
  say "bridge_check: FAIL (code $bridge_rc)"
  fail=$((fail + 1))
else
  say "bridge_check: PASS"
fi

section "File Propagation (incoming -> mt5 outputs)"
if [[ ! -f "$INCOMING_FILE" || ! -f "$MT5_5M_FILE" || ! -f "$MT5_5M_INTRADAY_FILE" ]]; then
  say "propagation_check: FAIL missing required files"
  fail=$((fail + 1))
else
  set +e
  python3 - <<'PY' "$INCOMING_FILE" "$MT5_5M_FILE" "$MT5_5M_INTRADAY_FILE" "$MAX_MT5_FILE_AGE_SEC"
import os, sys, time
incoming, out5, outi, max_age = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
now = time.time()
mi = os.path.getmtime(incoming)
m5 = os.path.getmtime(out5)
mi2 = os.path.getmtime(outi)
lag5 = m5 - mi
lagi = mi2 - mi
age_in = now - mi
print(f"incoming_age_sec: {age_in:.1f}")
print(f"incoming_to_out5_sec: {lag5:.3f}")
print(f"incoming_to_intraday_sec: {lagi:.3f}")
if age_in > max_age:
    print(f"RESULT propagation: FAIL incoming stale age={age_in:.1f}s > {max_age}s")
    raise SystemExit(31)
if lag5 < -2 or lagi < -2:
    print("RESULT propagation: WARN destination older than incoming")
    raise SystemExit(32)
print("RESULT propagation: PASS")
PY
  prop_rc=$?
  set -e
  if [[ $prop_rc -eq 32 ]]; then
    say "propagation_check: WARN output older than incoming"
    warn=$((warn + 1))
  elif [[ $prop_rc -ne 0 ]]; then
    say "propagation_check: FAIL (code $prop_rc)"
    fail=$((fail + 1))
  else
    say "propagation_check: PASS"
  fi
fi

section "Chart Gap Fill"
set +e
python3 - <<'PY' "$PROXY_BASE" "$SYMBOL" "$TIMEFRAMES" "$MAX_LIVE_AGE_SEC"
import json, sys, time, urllib.request
base, symbol, tf_str, max_age = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
now = int(time.time())
fail = 0
warn = 0
print("tf | status | candles | applied_tf | fallback | live_fill | age_s")
for tf in tf_str.split():
    url = f"{base}/market_causality/chart?symbol={symbol}&use_mt5=1&timeframe={tf}"
    try:
        with urllib.request.urlopen(url, timeout=80) as r:
            d = json.loads(r.read().decode())
        candles = d.get("candles") or []
        last_ts = int(candles[-1]["time"]) if candles else None
        age = (now - last_ts) if last_ts else None
        status = str(d.get("status"))
        fallback = bool(d.get("timeframe_fallback_applied"))
        live_fill = bool(d.get("live_gap_fill_applied"))
        applied = str(d.get("applied_timeframe"))
        print(f"{tf:>3} | {status:>6} | {len(candles):>6} | {applied:>9} | {str(fallback):>8} | {str(live_fill):>8} | {str(age):>6}")
        if status != "ok":
            fail += 1
            continue
        if not live_fill:
            warn += 1
        if age is None:
            fail += 1
            continue
        if age > max_age:
            fail += 1
            reason = d.get("live_gap_reason") or d.get("timeframe_fallback_reason") or "unknown"
            print(f"  stale_reason: {reason}")
    except Exception as exc:
        print(f"{tf:>3} | ERROR | {exc}")
        fail += 1
print(f"RESULT chart: fail={fail} warn={warn}")
raise SystemExit(0 if fail == 0 else 41)
PY
chart_rc=$?
set -e
if [[ $chart_rc -ne 0 ]]; then
  say "chart_check: FAIL"
  fail=$((fail + 1))
else
  say "chart_check: PASS"
fi

section "Live Price Endpoint"
set +e
live_json="$(curl -sS --max-time 10 "$API_BASE/market_causality/live_price?symbol=$SYMBOL&prefer_source=broker&broker_only=0&max_age_seconds=45")"
live_rc=$?
set -e
if [[ $live_rc -ne 0 || -z "$live_json" ]]; then
  say "live_price_check: FAIL (curl rc=$live_rc)"
  fail=$((fail + 1))
else
python3 - <<'PY' "$live_json"
import json, sys
d = json.loads(sys.argv[1])
print(f"status: {d.get('status')}")
print(f"source: {d.get('source')}")
print(f"price: {d.get('price')}")
print(f"spot: {d.get('spot')}")
print(f"elapsed_ms: {d.get('elapsed_ms')}")
PY
fi

section "Summary"
say "fail_count=$fail warn_count=$warn"
if [[ $fail -gt 0 ]]; then
  say "OVERALL: FAIL"
  exit 2
fi
if [[ $warn -gt 0 ]]; then
  say "OVERALL: WARN"
  exit 1
fi
say "OVERALL: PASS"
exit 0
