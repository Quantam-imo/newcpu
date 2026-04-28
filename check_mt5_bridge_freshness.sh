#!/bin/bash
# Check MT5 bridge freshness and chart readiness.
set -euo pipefail

# 5m feeds naturally update every 300s. Keep margin to avoid false FAIL loops.
MAX_LAG_SEC="${MT5_BRIDGE_MAX_LAG_SEC:-900}"
API_BASE="${MT5_BRIDGE_API_BASE:-http://localhost:8000}"
SYMBOL="${MT5_BRIDGE_SYMBOL:-XAUUSD}"
TIMEFRAME="${MT5_BRIDGE_TIMEFRAME:-5m}"
REQUIRE_MT5_SOURCE="${MT5_BRIDGE_REQUIRE_MT5_SOURCE:-1}"

json="$(curl --max-time 10 -sS "${API_BASE}/market_causality/mt5_bridge_status?symbol=${SYMBOL}&timeframe=${TIMEFRAME}")"

/workspaces/newcpu/.venv/bin/python - <<'PY' "$json" "$MAX_LAG_SEC" "$REQUIRE_MT5_SOURCE"
import json
import sys
import time

payload = json.loads(sys.argv[1])
max_lag = int(sys.argv[2])
require_mt5 = str(sys.argv[3]).strip().lower() not in {"0", "false", "no", "off"}
best = payload.get("best_live_quote") or {}
source = str(best.get("source") or "")
ts = best.get("ts")

if not payload.get("bridge_ready"):
    print("FAIL: bridge_ready=false")
    raise SystemExit(2)

if not source.startswith("mt5_"):
    msg = f"best source is not MT5 ({source or 'none'})"
    if require_mt5:
        print(f"FAIL: {msg}")
        raise SystemExit(2)
    print(f"WARN: {msg}")

if not isinstance(ts, (int, float)):
    print("FAIL: best_live_quote.ts missing")
    raise SystemExit(2)

lag = max(0, int(time.time() - int(ts)))
state = "PASS" if lag <= max_lag else "FAIL"
print(f"{state}: source={source} lag_sec={lag} max_lag_sec={max_lag}")
raise SystemExit(0 if lag <= max_lag else 2)
PY
