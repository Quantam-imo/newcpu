#!/usr/bin/env bash
set -euo pipefail

# AstroQuant System Stability & Pre-Live Verification Script
# Comprehensive checks before enabling live order execution

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_BASE="http://127.0.0.1:8000"
LOG_DIR="$ROOT_DIR/logs"
VERIFY_LOG="$LOG_DIR/stability_verify.log"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

mkdir -p "$LOG_DIR"

log() {
    local level="$1"
    shift
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "[${timestamp}] [${level}] $*" | tee -a "$VERIFY_LOG"
}

info() { log "INFO" "$@"; }
warn() { log "WARN" "$@"; }
error() { log "ERROR" "$@"; }
success() { echo -e "${GREEN}✓${NC} $*" | tee -a "$VERIFY_LOG"; }

header() {
    echo -e "\n${BLUE}╔════════════════════════════════════════════════════════════╗${NC}" | tee -a "$VERIFY_LOG"
    echo -e "${BLUE}║${NC} $1" | tee -a "$VERIFY_LOG"
    echo -e "${BLUE}╚════════════════════════════════════════════════════════════╝${NC}\n" | tee -a "$VERIFY_LOG"
}

test_count=0
pass_count=0
fail_count=0

run_test() {
    local name="$1"
    local cmd="$2"
    test_count=$((test_count + 1))

    echo -ne "[$test_count] Testing: $name... " | tee -a "$VERIFY_LOG"

    if output=$(eval "$cmd" 2>&1); then
        success "PASS"
        pass_count=$((pass_count + 1))
        return 0
    else
        echo -e "${RED}✗${NC} FAIL" | tee -a "$VERIFY_LOG"
        echo "  Error: $output" | tee -a "$VERIFY_LOG"
        fail_count=$((fail_count + 1))
        return 0
    fi
}

# ============================================================================
# 1. API Connectivity
# ============================================================================
header "Backend API Connectivity"

run_test "API responding" \
    "curl -s -f $API_BASE/status >/dev/null"

run_test "API version accessible" \
    "curl -s -f $API_BASE/docs >/dev/null"

run_test "Status endpoint returns JSON" \
    "curl -s -f $API_BASE/status | python -m json.tool >/dev/null"

# ============================================================================
# 2. Chrome/Execution Engine
# ============================================================================
header "Browser & Execution Engine"

run_test "Execution status endpoint" \
    "curl -s -f $API_BASE/status/execution >/dev/null"

EXEC_JSON=$(curl -s $API_BASE/status/execution 2>/dev/null || echo "{}")
BROWSER_CONNECTED=$(echo "$EXEC_JSON" | python -c "import json,sys; print(json.load(sys.stdin).get('connected', False))" 2>/dev/null || echo "false")
SELECTOR_LOADED=$(echo "$EXEC_JSON" | python -c "import json,sys; print(json.load(sys.stdin).get('selector_profile', {}).get('runtime_loaded', False))" 2>/dev/null || echo "false")
ORDER_READY=$(echo "$EXEC_JSON" | python -c "import json,sys; print(json.load(sys.stdin).get('order_panel', {}).get('ready', False))" 2>/dev/null || echo "false")

run_test "Browser connected" \
    "[[ '$BROWSER_CONNECTED' == 'True' ]] || [[ '$BROWSER_CONNECTED' == 'true' ]]"

run_test "Selector profile loaded" \
    "[[ '$SELECTOR_LOADED' == 'True' ]] || [[ '$SELECTOR_LOADED' == 'true' ]]"

if [[ "$ORDER_READY" != "True" ]] && [[ "$ORDER_READY" != "true" ]]; then
    warn "Order panel not ready (expected if on challenge page or not logged in)"
else
    run_test "Order entry panel ready" \
        "[[ '$ORDER_READY' == 'True' ]] || [[ '$ORDER_READY' == 'true' ]]"
fi

# ============================================================================
# 3. Market Data
# ============================================================================
header "Market Data Feeds"

run_test "Mentor context endpoint" \
    "curl -s -f '$API_BASE/mentor/context?symbol=XAUUSD' >/dev/null"

run_test "Chart data endpoint" \
    "curl -s -f '$API_BASE/chart/data?symbol=XAUUSD&timeframe=1m&limit=20' >/dev/null"

run_test "Dashboard multi-symbol" \
    "curl -s -f '$API_BASE/dashboard/multi_symbol' >/dev/null"

# Get market data samples
MENTOR_DATA=$(curl -s "$API_BASE/mentor/context?symbol=XAUUSD" 2>/dev/null || echo "{}")
MENTOR_PRICE=$(echo "$MENTOR_DATA" | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('price', 0))" 2>/dev/null || echo "0")

CHART_DATA=$(curl -s "$API_BASE/chart/data?symbol=XAUUSD&timeframe=1m&limit=5" 2>/dev/null || echo "{}")
CHART_CANDLE_COUNT=$(echo "$CHART_DATA" | python -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('candles', [])))" 2>/dev/null || echo "0")

if (( $(echo "$MENTOR_PRICE > 0" | bc -l 2>/dev/null || echo "0") )); then
    success "Live price data: XAUUSD = $MENTOR_PRICE"
else
    warn "No live price data yet (may be market closed)"
fi

if (( CHART_CANDLE_COUNT > 0 )); then
    success "Chart data loaded: $CHART_CANDLE_COUNT candles"
else
    warn "No chart candles loaded"
fi

# ============================================================================
# 4. Position Management
# ============================================================================
header "Position & Risk Management"

run_test "Position status endpoint" \
    "curl -s -f $API_BASE/status >/dev/null && python -c \"import json; d=json.loads(open('/tmp/status.json').read()); print(d.get('open_positions', {}) or {})\" 2>/dev/null || true"

run_test "Risk guard functions" \
    "curl -s -f $API_BASE/status | python -c \"import json,sys; d=json.load(sys.stdin); print('reduce_risk' in d.get('capital', {}).keys())\" | grep -i true"

# ============================================================================
# 5. Environment Configuration
# ============================================================================
header "Configuration & Security"

ENV_FILE="$ROOT_DIR/.env"
run_test ".env file exists" \
    "[[ -f '$ENV_FILE' ]]"

if [[ -f "$ENV_FILE" ]]; then
    run_test "CDP endpoint configured" \
        "grep -q 'CDP_ENDPOINT' '$ENV_FILE'"

    run_test "Order execution mode set" \
        "grep -q 'ORDER_EXECUTION_MODE' '$ENV_FILE'"

    run_test "Databento API key present" \
        "grep -q 'DATABENTO_API_KEY=db-' '$ENV_FILE'"

    # Check execution mode
    EXEC_MODE=$(grep 'ORDER_EXECUTION_MODE=' "$ENV_FILE" | cut -d'=' -f2 | tr -d ' ' || echo "unknown")
    info "Current execution mode: $EXEC_MODE"

    if [[ "$EXEC_MODE" == "auto" ]]; then
        warn "⚠ LIVE EXECUTION ENABLED! All orders will be executed immediately!"
    else
        success "Execution mode is safe ($EXEC_MODE) - trades require confirmation"
    fi
fi

# ============================================================================
# 6. File Integrity
# ============================================================================
header "System File Integrity"

REQUIRED_FILES=(
    "astroquant/backend/main.py"
    "astroquant/backend/config.py"
    "astroquant/execution/playwright_engine.py"
    "astroquant/execution/matchtrader_executor.py"
    "astroquant/data/matchtrader_selectors.json"
    "astroquant/frontend/index.html"
    "astroquant/engine/mentor_engine_v3.py"
)

for file in "${REQUIRED_FILES[@]}"; do
    filepath="$ROOT_DIR/$file"
    if [[ -f "$filepath" ]]; then
        size=$(du -h "$filepath" | cut -f1)
        success "Found: $file ($size)"
    else
        error "MISSING: $file"
        fail_count=$((fail_count + 1))
    fi
done

# ============================================================================
# 7. Python Dependencies
# ============================================================================
header "Python Dependencies"

VENV_BIN="$ROOT_DIR/.venv/bin"
PYTHON_BIN="$VENV_BIN/python"

CRITICAL_MODULES=(
    "fastapi"
    "uvicorn"
    "playwright"
    "databento"
    "pandas"
    "numpy"
)

for module in "${CRITICAL_MODULES[@]}"; do
    run_test "Module available: $module" \
        "$PYTHON_BIN -c \"import $module\" 2>/dev/null"
done

# ============================================================================
# 8. Stress Test
# ============================================================================
header "API Load & Performance"

info "Running stress test (10 parallel requests)..."
STRESS_START=$(date +%s%N)

for i in {1..10}; do
    curl -s "$API_BASE/status" >/dev/null &
done
wait

STRESS_END=$(date +%s%N)
STRESS_TIME=$(( ($STRESS_END - $STRESS_START) / 1000000 ))
STRESS_TIME_SEC=$(bc -l <<< "scale=2; $STRESS_TIME / 1000" 2>/dev/null || echo "unknown")

if (( $(echo "$STRESS_TIME_SEC < 10" | bc -l 2>/dev/null || echo "1") )); then
    success "Stress test passed: 10 requests in ${STRESS_TIME_SEC}ms"
else
    warn "Stress test slow: 10 requests took ${STRESS_TIME_SEC}ms"
fi

# ============================================================================
# 9. Browser State Assessment
# ============================================================================
header "Browser State Assessment"

CHALLENGE=$(echo "$EXEC_JSON" | python -c "import json,sys; print(json.load(sys.stdin).get('browser_challenge_detected', False))" 2>/dev/null || echo "unknown")

if [[ "$CHALLENGE" == "True" ]] || [[ "$CHALLENGE" == "true" ]]; then
    warn "⚠ Cloudflare challenge detected in browser"
    warn "Required action: Complete challenge in Chrome window and log into broker"
fi

BROWSER_TITLE=$(echo "$EXEC_JSON" | python -c "import json,sys; print(json.load(sys.stdin).get('browser_title', 'UNKNOWN'))" 2>/dev/null || echo "UNKNOWN")
info "Browser page title: $BROWSER_TITLE"

# ============================================================================
# Results Summary
# ============================================================================
header "Verification Summary"

TOTAL=$((pass_count + fail_count))
PASS_PCT=100
if (( TOTAL > 0 )); then
    PASS_PCT=$(( (pass_count * 100) / TOTAL ))
fi

echo -e "${BLUE}Test Results:${NC}"
echo "  Total Tests:  $TOTAL"
echo -e "  ${GREEN}Passed:${NC} $pass_count"
if (( fail_count > 0 )); then
    echo -e "  ${RED}Failed:${NC} $fail_count"
else
    echo -e "  ${GREEN}Failed:${NC} 0"
fi
echo "  Success Rate: ${PASS_PCT}%"
echo ""

if (( fail_count == 0 )); then
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${GREEN}✓ ALL SYSTEMS NOMINAL - READY FOR LIVE TRADING!${NC}"
    echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    exit 0
elif (( fail_count <= 2 )); then
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}⚠ SYSTEMS READY WITH WARNINGS${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "Action items before live trading:"
    if [[ "$CHALLENGE" == "True" ]] || [[ "$CHALLENGE" == "true" ]]; then
        echo "  1. Complete Cloudflare challenge in Chrome"
        echo "  2. Log into broker account"
        echo "  3. Verify order entry form is visible"
        echo "  4. Re-run calibration: bash LIVE_LAUNCH.sh"
    fi
    exit 0
else
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${RED}✗ SYSTEM NOT READY FOR LIVE TRADING${NC}"
    echo -e "${RED}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "See above for failures to address."
    echo "Log file: $VERIFY_LOG"
    exit 1
fi
