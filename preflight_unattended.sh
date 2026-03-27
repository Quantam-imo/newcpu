#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

print_bridge_diagnostics() {
  local bridge_json="$1"
  BRIDGE_JSON="$bridge_json" "$ROOT_DIR/.venv/bin/python" - <<'PY'
import json
import os

payload = os.environ.get("BRIDGE_JSON", "")
try:
    data = json.loads(payload)
except Exception:
    print("INFO: Bridge diagnostics unavailable (invalid JSON)")
    raise SystemExit(0)

order_panel = data.get("order_panel") or {}
quote = data.get("quote") or {}

lines = [
    f"INFO: Bridge status={data.get('status')}",
    f"INFO: Broker tab title={data.get('broker_tab_title') or 'n/a'}",
    f"INFO: Broker tab url={data.get('broker_tab_url') or 'n/a'}",
    f"INFO: Challenge detected={bool(data.get('challenge_detected'))}",
    f"INFO: Challenge reason={data.get('challenge_reason') or 'n/a'}",
    f"INFO: Order panel reason={order_panel.get('reason') or 'n/a'}",
    f"INFO: Order panel ready={bool(order_panel.get('ready'))}",
    f"INFO: Quote present={bool(quote and (quote.get('mid') is not None or quote.get('last') is not None or quote.get('price') is not None))}",
]
for line in lines:
    print(line)
PY
}

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  AstroQuant Unattended Preflight${NC}"
echo -e "${BLUE}  API Base: $API_BASE${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

info "Running strict baseline preflight first"
if "$ROOT_DIR/preflight_strict.sh" "$API_BASE"; then
  pass "Strict preflight baseline passed"
else
  fail "Strict preflight baseline failed"
fi

if bridge_json=$(curl -fsS --max-time 8 "$API_BASE/status/broker_bridge" 2>/dev/null); then
  pass "Broker bridge endpoint reachable"

  bridge_eval=$(BRIDGE_JSON="$bridge_json" "$ROOT_DIR/.venv/bin/python" - <<'PY'
import json
import os

payload = os.environ.get("BRIDGE_JSON", "")
try:
    data = json.loads(payload)
except Exception:
    print("BAD_JSON")
    raise SystemExit(0)

debugger_reachable = bool(data.get("debugger_reachable"))
same_browser_mode = bool(data.get("same_browser_mode"))
bridge_ready = bool(data.get("bridge_ready"))
tabs_broker = int(data.get("tabs_broker") or 0)
tabs_dashboard = int(data.get("tabs_dashboard") or 0)
challenge_detected = bool(data.get("challenge_detected"))
challenge_reason = str(data.get("challenge_reason") or "")
broker_title = str(data.get("broker_tab_title") or "")
quote = data.get("quote") or {}
order_panel = data.get("order_panel") or {}
has_quote = quote.get("mid") is not None or quote.get("last") is not None or quote.get("price") is not None
panel_ready = bool(order_panel.get("ready"))
reason = str(order_panel.get("reason") or "")

if not debugger_reachable:
    print("NO_DEBUGGER")
elif tabs_broker < 1:
    print("NO_BROKER_TAB")
elif tabs_dashboard < 1:
    print("NO_DASHBOARD_TAB")
elif not same_browser_mode:
    print("SPLIT_BROWSER_SESSION")
elif challenge_detected:
  suffix = f":{challenge_reason}" if challenge_reason else ""
  if broker_title:
    suffix = f"{suffix}:{broker_title}"
  print(f"CHALLENGE{suffix}")
elif bridge_ready or has_quote or panel_ready:
    print("READY")
else:
    if reason:
        print(f"NOT_READY:{reason}")
    else:
        print("NOT_READY:no_quote_or_panel")
PY
)

  case "$bridge_eval" in
    READY)
      pass "Broker bridge is healthy for unattended execution"
      ;;
    BAD_JSON)
      fail "Broker bridge endpoint returned invalid JSON"
      ;;
    NO_DEBUGGER)
      fail "CDP debugger is not reachable from broker bridge"
      ;;
    NO_BROKER_TAB)
      fail "Broker tab missing from remote-debug Chrome session"
      ;;
    NO_DASHBOARD_TAB)
      fail "AstroQuant dashboard tab missing from remote-debug Chrome session"
      ;;
    SPLIT_BROWSER_SESSION)
      fail "Broker and dashboard tabs are not in the same browser session"
      ;;
    CHALLENGE:*)
      fail "Broker bridge blocked by challenge page (${bridge_eval#CHALLENGE:})"
      print_bridge_diagnostics "$bridge_json"
      ;;
    CHALLENGE)
      fail "Broker bridge blocked by challenge page"
      print_bridge_diagnostics "$bridge_json"
      ;;
    NOT_READY:*)
      fail "Broker bridge reachable but not execution-ready (${bridge_eval#NOT_READY:})"
      print_bridge_diagnostics "$bridge_json"
      ;;
    *)
      fail "Broker bridge returned unexpected evaluation result: $bridge_eval"
      print_bridge_diagnostics "$bridge_json"
      ;;
  esac
else
  fail "Cannot reach $API_BASE/status/broker_bridge"
fi

echo ""
echo "Summary: $PASS_COUNT passed, $FAIL_COUNT failed"

if [[ $FAIL_COUNT -gt 0 ]]; then
  echo -e "${RED}UNATTENDED PREFLIGHT: BLOCKED${NC}"
  exit 1
fi

echo -e "${GREEN}UNATTENDED PREFLIGHT: READY${NC}"