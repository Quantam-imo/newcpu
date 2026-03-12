#!/bin/bash
# =============================================================================
# AstroQuant Pre-Launch Health Check
# Validates all critical systems before live trading
# =============================================================================

set -e

API_BASE="${1:-http://127.0.0.1:8000}"
RESULTS_FILE="PRE_LAUNCH_CHECK.log"
PASSED=0
FAILED=0
WARNINGS=0

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_pass() {
    echo -e "${GREEN}✓ PASS${NC}: $1" | tee -a "$RESULTS_FILE"
    PASSED=$((PASSED + 1))
}

log_fail() {
    echo -e "${RED}✗ FAIL${NC}: $1" | tee -a "$RESULTS_FILE"
    FAILED=$((FAILED + 1))
}

log_warn() {
    echo -e "${YELLOW}⚠ WARN${NC}: $1" | tee -a "$RESULTS_FILE"
    WARNINGS=$((WARNINGS + 1))
}

log_info() {
    echo -e "${BLUE}ℹ INFO${NC}: $1" | tee -a "$RESULTS_FILE"
}

echo "AstroQuant Pre-Launch Health Check" > "$RESULTS_FILE"
echo "API Base: $API_BASE" >> "$RESULTS_FILE"
echo "Timestamp: $(date)" >> "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  AstroQuant Pre-Launch Health Check${NC}"
echo -e "${BLUE}  API Base: $API_BASE${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# =============================================================================
# Test 1: Backend Connectivity
# =============================================================================
echo -e "${YELLOW}[1/8] Testing Backend Connectivity...${NC}"

if timeout 5 curl -s "$API_BASE/status" > /dev/null; then
    log_pass "Backend API responding at $API_BASE"
else
    log_fail "Cannot reach backend at $API_BASE"
    echo "Fix: Start backend with: cd /workspaces/newcpu/astroquant && /workspaces/newcpu/.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"
fi
echo ""

# =============================================================================
# Test 2: Frontend Load
# =============================================================================
echo -e "${YELLOW}[2/8] Testing Frontend Load...${NC}"

if timeout 5 curl -s "$API_BASE/frontend" | grep -q "Performance Dashboard"; then
    log_pass "Frontend loads and contains Performance Dashboard"
else
    log_warn "Frontend loads but Performance Dashboard UI may not be present"
fi
echo ""

# =============================================================================
# Test 3: Health Status
# =============================================================================
echo -e "${YELLOW}[3/8] Checking System Health (/status)...${NC}"

STATUS_RESPONSE=$(timeout 5 curl -s "$API_BASE/status")

if [ -z "$STATUS_RESPONSE" ]; then
    log_fail "No response from /status endpoint"
else
    log_pass "Status endpoint responding"
    
    # Check for key fields
    if echo "$STATUS_RESPONSE" | grep -q "\"system_health\""; then
        log_pass "System health field present"
    else
        log_warn "System health field missing from status"
    fi
    
    # Check connection status
    if echo "$STATUS_RESPONSE" | grep -q "\"connected_broker\""; then
        CONNECTED=$(echo "$STATUS_RESPONSE" | grep "connected_broker" | grep -o "true\|false")
        if [ "$CONNECTED" = "true" ]; then
            log_pass "Broker connection: CONNECTED"
        else
            log_warn "Broker connection: DISCONNECTED (needs CDP restoration)"
        fi
    else
        log_warn "Broker connection status field missing"
    fi
fi
echo ""

# =============================================================================
# Test 4: Mentor Data Availability
# =============================================================================
echo -e "${YELLOW}[4/8] Testing Mentor Data (/mentor)...${NC}"

MENTOR_RESPONSE=$(timeout 10 curl -s "$API_BASE/mentor/context?symbol=XAUUSD")

if [ -z "$MENTOR_RESPONSE" ]; then
    log_fail "No response from /mentor endpoint"
else
    if echo "$MENTOR_RESPONSE" | grep -q "\"context\""; then
        log_pass "Mentor context endpoint responding"
        
        # Check for data
        if echo "$MENTOR_RESPONSE" | grep -q "\"price\""; then
            PRICE=$(echo "$MENTOR_RESPONSE" | grep -o '"price":[0-9.]*' | head -1 | cut -d: -f2)
            if [ "$PRICE" = "0" ] || [ -z "$PRICE" ]; then
                log_warn "Mentor price is placeholder/zero (data feed may not be connected)"
            else
                log_pass "Mentor price data: $PRICE"
            fi
        else
            log_warn "Price field not found in mentor response"
        fi
    else
        log_fail "Mentor endpoint not responding with context"
    fi
fi
echo ""

# =============================================================================
# Test 5: Chart Data
# =============================================================================
echo -e "${YELLOW}[5/8] Testing Chart Data (/chart/data)...${NC}"

CHART_RESPONSE=$(timeout 10 curl -s "$API_BASE/chart/data?symbol=XAUUSD&timeframe=1m&limit=5")

if [ -z "$CHART_RESPONSE" ]; then
    log_fail "No response from /chart/data endpoint"
else
    if echo "$CHART_RESPONSE" | grep -q "\"candles\""; then
        log_pass "Chart data endpoint responding"
        
        # Count candles
        CANDLE_COUNT=$(echo "$CHART_RESPONSE" | grep -o '"time"' | wc -l)
        if [ "$CANDLE_COUNT" -gt 0 ]; then
            log_pass "Chart contains $CANDLE_COUNT candles"
        else
            log_warn "Chart response present but no candle data"
        fi
    else
        log_fail "Chart endpoint not returning candle data"
    fi
fi
echo ""

# =============================================================================
# Test 6: Order Entry System
# =============================================================================
echo -e "${YELLOW}[6/8] Checking Order Entry System...${NC}"

# Try to get execution status
EXEC_STATUS=$(timeout 5 curl -s "$API_BASE/status/execution" 2>/dev/null || echo "{}")

if echo "$EXEC_STATUS" | grep -q "execution_status"; then
    STATUS=$(echo "$EXEC_STATUS" | grep -o '"execution_status":"[^"]*"' | cut -d'"' -f4)
    if [ "$STATUS" = "CONNECTED" ]; then
        log_pass "Order execution system: CONNECTED"
    else
        log_warn "Order execution system: $STATUS (needs CDP connection)"
        echo "  → Run DOM calibration once CDP is restored"
    fi
else
    log_warn "Execution status endpoint not available (pre-CDP phase expected)"
fi
echo ""

# =============================================================================
# Test 7: Performance Caching
# =============================================================================
echo -e "${YELLOW}[7/8] Testing Performance Caching System...${NC}"

# Make same request twice, second should be faster
START=$(date +%s%N)
curl -s "$API_BASE/mentor/context?symbol=XAUUSD" > /dev/null
FIRST_TIME=$(($(date +%s%N) - START))

START=$(date +%s%N)
curl -s "$API_BASE/mentor/context?symbol=XAUUSD" > /dev/null
SECOND_TIME=$(($(date +%s%N) - START))

log_info "First request: $((FIRST_TIME / 1000000))ms"
log_info "Second request: $((SECOND_TIME / 1000000))ms"

# Second should be significantly faster due to caching
if [ "$SECOND_TIME" -lt "$FIRST_TIME" ]; then
    IMPROVEMENT=$(( (FIRST_TIME - SECOND_TIME) * 100 / FIRST_TIME ))
    log_pass "Response caching working ($IMPROVEMENT% faster)"
else
    log_warn "Second request not significantly faster (caching may not be active)"
fi
echo ""

# =============================================================================
# Test 8: File System Integrity
# =============================================================================
echo -e "${YELLOW}[8/8] Checking File System Integrity...${NC}"

# Check critical files exist
CRITICAL_FILES=(
    "astroquant/frontend/index.html"
    "astroquant/frontend/api.js"
    "astroquant/frontend/mentor.js"
    "astroquant/frontend/chart.js"
    "astroquant/backend/main.py"
    "astroquant/config/production_config.py"
)

for file in "${CRITICAL_FILES[@]}"; do
    if [ -f "$file" ]; then
        SIZE=$(du -h "$file" | cut -f1)
        log_pass "Required file present: $file ($SIZE)"
    else
        log_fail "Critical file missing: $file"
    fi
done
echo ""

# =============================================================================
# Summary
# =============================================================================
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Test Results Summary${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All critical tests passed!${NC}"
else
    echo -e "${RED}✗ ${FAILED} critical tests failed${NC}"
fi

echo ""
echo "Results: $PASSED passed, $FAILED failed, $WARNINGS warnings"
echo ""

if [ $FAILED -gt 0 ]; then
    echo -e "${RED}DEPLOYMENT STATUS: NOT READY FOR LIVE TRADING${NC}"
    echo ""
    echo "Required fixes before proceeding:"
    grep "^✗" "$RESULTS_FILE" | sed 's/✗ FAIL: /  • /'
    exit 1
fi

if [ $WARNINGS -gt 0 ]; then
    echo -e "${YELLOW}DEPLOYMENT STATUS: READY (with conditions)${NC}"
    echo ""
    echo "Recommended actions:"
    grep "^⚠" "$RESULTS_FILE" | sed 's/⚠ WARN: /  • /'
    echo ""
    echo "To proceed with live trading:"
    echo "  1. Address warnings above"
    echo "  2. Run final drift dry-run (execute=false mode)"
    echo "  3. Verify position reconciliation"
    exit 0
fi

echo -e "${GREEN}DEPLOYMENT STATUS: READY FOR LIVE TRADING${NC}"
echo ""
echo "Next steps:"
echo "  1. Review DEPLOYMENT_VALIDATION.txt"
echo "  2. Run micro-lot dry-run"
echo "  3. Monitor position entry/exit"
echo "  4. Enable live trading once comfortable"
echo ""
echo "Results logged to: $RESULTS_FILE"
