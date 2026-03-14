#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$ROOT_DIR/.env"
API_BASE="${1:-http://127.0.0.1:8000}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0

pass() {
  echo -e "${GREEN}PASS${NC}: $*"
  PASS_COUNT=$((PASS_COUNT + 1))
}

fail() {
  echo -e "${RED}FAIL${NC}: $*"
  FAIL_COUNT=$((FAIL_COUNT + 1))
}

info() {
  echo -e "${BLUE}INFO${NC}: $*"
}

extract_env_var() {
  local key="$1"
  if [[ ! -f "$ENV_FILE" ]]; then
    echo ""
    return
  fi
  local line
  line=$(grep -E "^${key}=" "$ENV_FILE" | tail -1 || true)
  if [[ -z "$line" ]]; then
    echo ""
    return
  fi
  line="${line#*=}"
  line="${line%\"}"
  line="${line#\"}"
  line="${line%\'}"
  line="${line#\'}"
  echo "$line"
}

looks_placeholder() {
  local value="${1,,}"
  [[ -z "$value" || "$value" == *"your_"* || "$value" == *"changeme"* || "$value" == *"placeholder"* || "$value" == *"example"* || "$value" == "none" || "$value" == "null" ]]
}

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  AstroQuant Strict Preflight${NC}"
echo -e "${BLUE}  API Base: $API_BASE${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo ""
info "Validating environment file"
if [[ -f "$ENV_FILE" ]]; then
  pass "Found .env at $ENV_FILE"
else
  fail "Missing .env at $ENV_FILE"
fi

databento_key="$(extract_env_var "DATABENTO_API_KEY")"
if looks_placeholder "$databento_key"; then
  fail "DATABENTO_API_KEY missing or placeholder"
elif [[ "$databento_key" != db-* ]]; then
  fail "DATABENTO_API_KEY format invalid (expected prefix db-)"
else
  pass "DATABENTO_API_KEY looks valid"
fi

cdp_url="$(extract_env_var "EXECUTION_BROWSER_CDP_URL")"
if [[ -z "$cdp_url" ]]; then
  cdp_url="$(extract_env_var "CDP_ENDPOINT")"
fi

if looks_placeholder "$cdp_url"; then
  fail "CDP endpoint missing from EXECUTION_BROWSER_CDP_URL/CDP_ENDPOINT"
else
  pass "CDP endpoint configured: $cdp_url"
fi

cdp_host=""
cdp_port=""
if [[ "$cdp_url" =~ ^wss?://([^/:]+):([0-9]+) ]]; then
  cdp_host="${BASH_REMATCH[1]}"
  cdp_port="${BASH_REMATCH[2]}"
else
  fail "CDP endpoint must be ws://host:port or wss://host:port"
fi

if [[ -n "$cdp_host" && -n "$cdp_port" ]]; then
  cdp_probe_url="http://${cdp_host}:${cdp_port}/json/version"
  if cdp_json=$(curl -fsS --max-time 5 "$cdp_probe_url" 2>/dev/null); then
    if echo "$cdp_json" | grep -q "webSocketDebuggerUrl"; then
      pass "CDP probe reachable at $cdp_probe_url"
    else
      fail "CDP probe responded but webSocketDebuggerUrl missing"
    fi
  else
    fail "Cannot reach CDP probe at $cdp_probe_url"
  fi
fi

if exec_json=$(curl -fsS --max-time 8 "$API_BASE/status/execution" 2>/dev/null); then
  pass "Execution status endpoint reachable"

  eval_result=$(printf '%s' "$exec_json" | /workspaces/newcpu/.venv/bin/python - <<'PY'
import json,sys
try:
    data=json.load(sys.stdin)
except Exception:
    print("BAD_JSON")
    raise SystemExit(0)
status=str(data.get("execution_status") or "").upper()
connected=bool(data.get("connected"))
panel_ready=bool((data.get("order_panel") or {}).get("ready"))
if connected or status == "CONNECTED" or panel_ready:
    print("CONNECTED")
else:
    print("DISCONNECTED")
PY
)

  if [[ "$eval_result" == "CONNECTED" ]]; then
    pass "Execution connection is live (CONNECTED/panel_ready)"
  elif [[ "$eval_result" == "BAD_JSON" ]]; then
    fail "Execution endpoint returned invalid JSON"
  else
    fail "Execution is not live yet (status endpoint indicates disconnected)"
  fi
else
  fail "Cannot reach $API_BASE/status/execution"
fi

echo ""
echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed"

if [[ $FAIL_COUNT -gt 0 ]]; then
  echo -e "${RED}STRICT PREFLIGHT: BLOCKED${NC}"
  exit 1
fi

echo -e "${GREEN}STRICT PREFLIGHT: READY${NC}"
