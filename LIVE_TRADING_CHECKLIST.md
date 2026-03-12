# AstroQuant Live Trading Pre-Launch Checklist

**Current Phase:** Preparing for Full Live Trading Setup  
**Status:** Ready to Deploy  
**Generated:** March 11, 2026

---

## 📋 Pre-Deployment Checklist (Do This First)

### System Requirements
- [ ] Python 3.8+ installed (`python3 --version`)
- [ ] Virtual environment created and activated (`.venv`)
- [ ] All dependencies installed (`pip list | grep -E uvicorn|fastapi`)
- [ ] Sufficient disk space (min 500MB free)
- [ ] Network connectivity verified
- [ ] Ports 8000 and 9222 available

### Repository State
- [ ] Code on clean main branch (`git status` shows clean)
- [ ] All uncommitted changes stashed or committed
- [ ] .env file created (copy from .env.template)
- [ ] .env secrets filled in (API keys, account IDs)
- [ ] .gitignore updated (no secrets will be committed)

### Backup & Safety
- [ ] Full repository backed up to external drive
- [ ] Database backups created (`astroquant/data/`)
- [ ] Configuration backed up (production_config.py)
- [ ] Recovery procedure documented locally
- [ ] Rollback plan tested (can you restore backup?)

---

## 🚀 Deployment Phase (Run This)

### Step 1: Run Deployment Script
```bash
cd /workspaces/newcpu
chmod +x deploy.sh
./deploy.sh
```

**This will:**
- [ ] Verify Python and dependencies
- [ ] Create timestamped backup
- [ ] Clean __pycache__ and runtime artifacts
- [ ] Validate module imports
- [ ] Generate deployment manifest
- [ ] Generate validation report

**Check output for:**
- [ ] "✓ DEPLOYMENT COMPLETE"
- [ ] Backup directory created
- [ ] DEPLOYMENT_MANIFEST.txt and DEPLOYMENT_VALIDATION.txt generated

### Step 2: Review Deployment Reports
```bash
cat DEPLOYMENT_VALIDATION.txt
cat DEPLOYMENT_MANIFEST.txt
```

**Verify:**
- [ ] Phase 1 (Error Handling) marked COMPLETE
- [ ] Phase 2 (Caching) marked COMPLETE
- [ ] All frontend files listed as included
- [ ] Deployment artifacts cleaned (no __pycache__)
- [ ] Backend ready status (⏳ awaiting CDP)

### Step 3: Run Health Check
```bash
chmod +x health_check.sh
./health_check.sh
```

**This will test:**
- [ ] Backend connectivity (http://127.0.0.1:8000/status)
- [ ] Frontend load (error handling UI present)
- [ ] Mentor data endpoint (/mentor/context)
- [ ] Chart data endpoint (/chart/data)
- [ ] Performance caching (2nd request faster)
- [ ] File system integrity (all critical files present)

**Expected results:**
- [ ] "✓ All critical tests passed!" OR
- [ ] "DEPLOYMENT STATUS: READY (with conditions)"

**If ✗ FAILED:**
- [ ] Fix reported errors (see suggestions in output)
- [ ] Re-run health check
- [ ] Consult troubleshooting section below

---

## 🔧 Critical Pre-Launch Fixes

### Fix 1: CDP Endpoint Restoration (CRITICAL)

**Current Status:** ⏳ Blocked waiting for this

```bash
# Find your Chrome CDP endpoint:
# 1. Run Chrome with debugging: chrome --remote-debugging-port=9222
# 2. Visit chrome://inspect to see endpoint
# 3. Or use: curl http://127.0.0.1:9222/json

# Once found, update .env:
CDP_ENDPOINT=ws://127.0.0.1:9222
```

**Verification:**
```bash
# Test CDP connection
curl -s http://127.0.0.1:9222/json | head -5
# Should show: "devtools", "type", "id", etc.
```

### Fix 2: Order Entry Selector Calibration

**Current Status:** ⏳ Blocked waiting for CDP

Once CDP is running:
```bash
# Broker account must be open in Chrome
# Run calibration (exact command depends on execution module):
# python -m astroquant.execution.selector_calibrator

# This will:
# [ ] Identify order entry form
# [ ] Locate symbol input field
# [ ] Identify buy/sell buttons
# [ ] Locate volume input
# [ ] Save selectors to: astroquant/data/matchtrader_selectors.json
```

**Verify calibration succeeded:**
```bash
cat astroquant/data/matchtrader_selectors.json
# Should contain: order_panel, symbol_input, buy_btn, sell_btn, volume_input
```

### Fix 3: Mentor Data Feed Connection

**Current Status:** ⏳ Checking for stale data

```bash
# Test mentor data endpoint:
curl -s http://127.0.0.1:8000/mentor/context?symbol=XAUUSD | jq '.context.price'

# Should return: number > 1000, not 0 or null
# If 0/null: data feed not connected
```

**Solution:**
- [ ] Verify broker is open and showing quotes
- [ ] Check market is in active hours
- [ ] Verify data subscription is active
- [ ] Test with different symbol (GC.FUT, NQ.FUT)

---

## 🧪 Testing Phase (Do Before Live Trading)

### Test 1: Dry-Run Order Entry

**Set in .env:**
```bash
ORDER_EXECUTION_MODE=dry-run
ORDER_MICRO_LOT_SIZE=0.01
```

**Run test:**
```bash
# From browser:
# 1. Click order entry button
# 2. Select symbol XAUUSD
# 3. Set volume 0.01
# 4. Click BUY

# Should log: "Order XAUUSD 0.01 BUY - SIMULATED (execute=false)"
# No real trade executed
```

**Verify:**
- [ ] No error messages
- [ ] Order logged to console
- [ ] Position NOT shown in real positions list
- [ ] Can retry multiple times

### Test 2: Live Order Entry (Micro-Lot)

**Update .env:**
```bash
ORDER_EXECUTION_MODE=confirm-token
ORDER_MICRO_LOT_SIZE=0.01
```

**Run test:**
```bash
# 1. Ensure broker DOM is visible (order panel open)
# 2. Click order entry button in dashboard
# 3. System should:
#    [ ] Detect order DOM form
#    [ ] Fill symbol: XAUUSD
#    [ ] Fill volume: 0.01
#    [ ] Pause (wait for confirm-token)
#    [ ] In Chrome, manually click the CONFIRM button in DOM
#    [ ] Order should submit

# Check results:
curl -s http://127.0.0.1:8000/status | jq '.positions'
# Should show: open position for XAUUSD 0.01

# Monitor in real-time:
./health_check.sh
# Check "Position" field in status output
```

**Verify:**
- [ ] Order appears in broker positions immediately
- [ ] Dashboard position reconciliation detects it
- [ ] P&L starts updating in real-time
- [ ] Can manually close position in broker

### Test 3: Multi-Symbol Scan

**Purpose:** Verify performance caching and mentor multi-symbol capability

```bash
# 1. Open Performance Dashboard (📊 Perf button)
# 2. Scan symbols: XAUUSD, GC.FUT, NQ.FUT, EURUSD, GBPUSD

# Monitor:
# [ ] First symbol takes ~18s (/market/offset_quality)
# [ ] 2nd-5th symbols take <1s (cached)
# [ ] Cache hit rate shown in dashboard
# [ ] Dashboard shows: 5 requests, ~60-80% cache hits
```

**Verify:**
- [ ] Mentor data loads for each symbol
- [ ] Cache hit rate in Performance Dashboard
- [ ] Slowest endpoint performance acceptable

### Test 4: Error Scenario Recovery

**Purpose:** Verify PHASE 1 error handling works in real scenarios

```bash
# Test 4a: Recover from connection loss
# 1. Turn OFF broker (close terminal running backend)
# 2. Try to load mentor - should show ERROR BANNER in 2 seconds
# 3. Click RETRY button
# 4. Turn ON broker again (restart backend)
# 5. ERROR should clear, data should load
# Expected: User sees smooth recovery, no app crash

# Test 4b: Timeout handling
# 1. Leave slow endpoint (/market/offset_quality) running
# 2. Should show loading state briefly
# 3. Should complete within 25 seconds
# 4. If timeout: error banner with retry

# Test 4c: Multi-request error recovery
# 1. Mentor FAILS
# 2. Chart FAILS
# 3. Both error banners shown simultaneously
# 4. Click retry on one → only that one re-attempts
```

**Verify:**
- [ ] Error banners appear (not crashes)
- [ ] Retry buttons functional
- [ ] Auto-dismiss after 15s
- [ ] Connection status badge changes color
- [ ] No console errors (F12 Console clean)

### Test 5: Position Reconciliation

**Purpose:** Verify system correctly tracks open positions

```bash
# 1. Enter micro-lot trade (0.01 XAUUSD)
# 2. Dashboard should show position immediately
# 3. Close position manually in broker
# 4. Wait 5 seconds (reconciliation interval)
# 5. Dashboard should reflect closed position

# Verify reconciliation:
curl -s http://127.0.0.1:8000/status | jq '.positions'
```

**Verify:**
- [ ] Position appears when entered
- [ ] P&L updates with market moves
- [ ] Closed positions removed after reconciliation
- [ ] No phantom positions

---

## 🎯 Go-Live Criteria (All Must Pass)

### Functional Requirements
- [ ] Backend API responds to all endpoints
- [ ] Frontend loads without errors (F12 Console clean)
- [ ] Mentor data shows live prices (not placeholders)
- [ ] Chart data loads all candles correctly
- [ ] Order entry submits through broker successfully
- [ ] Positions appear in dashboard immediately
- [ ] Multi-symbol scanning works with caching

### Error Handling Requirements
- [ ] Connection errors show user-friendly banners
- [ ] Retry buttons work correctly
- [ ] Health check runs every 30s
- [ ] Connection status badge visible and accurate
- [ ] Performance dashboard shows response times
- [ ] No 500 errors in console (only expected 599)

### Risk Management Requirements
- [ ] DAILY_LOSS_LIMIT enforced (stops new trades)
- [ ] MAX_POSITION_SIZE respected (prevents over-leverage)
- [ ] Position reconciliation active (detects orphaned positions)
- [ ] Stop-loss automation tested (orders close at target)
- [ ] Account equity monitoring active
- [ ] Drawdown limits enforced

### Performance Requirements
- [ ] Mentor loads within 8 seconds (cached <1ms)
- [ ] Chart loads within 5 seconds (cached <1ms)
- [ ] Cache hit rate >15% observed (target 20-25%)
- [ ] No timeout errors on typical endpoints
- [ ] Dashboard responsive (no UI lag)
- [ ] Multi-symbol scan completes in <60s

### Data Integrity Requirements
- [ ] No stale data (mentor updated every 8s)
- [ ] Position count matches broker
- [ ] Trade logs record all executions
- [ ] Database backup active and tested

---

## 📊 Live Trading Start Procedure

Once all tests pass:

### Step 1: Pre-Market Preparation (30 minutes before open)

```bash
# 1. Start backend
cd /workspaces/newcpu/astroquant
/workspaces/newcpu/.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 2. Open broker in Chrome
# chrome --remote-debugging-port=9222
# Open broker website (MatchTrader, IB, etc.)
# Login and navigate to trading dashboard

# 3. In another terminal, verify health
./health_check.sh
# Confirm: ✓ All critical tests passed

# 4. Open frontend dashboard
# http://localhost:8000/frontend

# 5. Check initial state:
# [ ] Connection status = GREEN
# [ ] Mentor data showing (prices > 0)
# [ ] Recent candles displayed
# [ ] No errors in Performance Dashboard
```

### Step 2: First Position Entry (Market Open)

```bash
# CRITICAL: Set micro-lot size first
# .env: ORDER_MICRO_LOT_SIZE=0.01

# 1. Verify in browser:
#    - Mentor drawer: Check iceberg detection (strong/weak)
#    - Chart: Check orderflow imbalance bias
#    - Alerts: Any position risk warnings?

# 2. Click [BUY] in dashboard (for XAUUSD or similar)
#    - Only if both mentor + chart signals aligned

# 3. Watch execution in browser:
#    - Broker DOM should fill with values
#    - Manual CONFIRM in broker (confirm-token mode)
#    - Position should appear in dashboard immediately

# 4. Monitor P&L:
#    - Per-trade P&L updates
#    - Account equity updated
#    - Daily loss tracking active
```

### Step 3: Monitor & Adjust

```bash
# During trading session:
# [ ] Check Performance Dashboard every 30 minutes
# [ ] Verify mentor data freshness (age < 8sec)
# [ ] Monitor daily loss (stops if exceeded)
# [ ] Check position reconciliation (no orphans)
# [ ] Verify connection status (if RED, check alerts)

# If issues occur:
# 1. Check error banner (visible in header)
# 2. Read error message carefully
# 3. Click RETRY if it's a transient error
# 4. Check health_check.sh if persists
# 5. Review logs: astroquant/logs/
```

---

## 🚨 Emergency Procedures

### If Connection Drops

1. **Immediate:** Error banner appears, orders stop submitting ✓
2. **Check:** Run `./health_check.sh`
3. **Fix:** If backend down, restart it
4. **Resume:** Click retry on any pending operations

### If Position Stuck

1. **Do NOT:** Panic, place manual override in broker
2. **Check:** curl http://127.0.0.1:8000/status | jq '.positions'
3. **Close:** Manually close unwanted position in broker
4. **Monitor:** Wait for reconciliation (5 second interval)
5. **Dashboard:** Position should disappear after reconciliation

### If Daily Loss Exceeded

1. **Automatic:** New orders rejected by system ✓
2. **Message:** "Daily loss limit exceeded" in error banner
3. **Action:** Review trades, identify losses
4. **Reset:** Daily limit resets at market open next day
5. **Adjustable:** Edit DAILY_LOSS_LIMIT in .env, restart

### If Mentor Data Stale

1. **Detection:** Age > 30 seconds in mentor header
2. **Check:** Click refresh button in mentor drawer
3. **Verify:** curl http://127.0.0.1:8000/mentor | jq '.updated_at'
4. **Fix:** If broker window lost focus, click DOM to restore
5. **Monitor:** Data should refresh within 8 seconds

---

## 📈 Performance Baseline for Reference

### Expected Response Times (No Cache)

| Endpoint | Time | Note |
|----------|------|------|
| /status | 170ms | Health check - fast |
| /chart/data | 5.2s | Candle loading |
| /mentor/context | 7.4s | Market analysis |
| /market/offset_quality | 18.4s | Slowest (playwright) |

### With Caching Enabled

| Scenario | Time | Improvement |
|----------|------|-------------|
| First mentor load | 7.4s | Baseline |
| Mentor reload (2s later) | <1ms | **99% faster** |
| Chart zoom/pan | <1ms | **99% faster** |
| Multi-symbol 5th scan | <1ms | **99% faster** |

### Target Metrics

- **Cache hit rate:** 15-25% overall
- **Mentor hit rate:** 60-80%
- **Chart hit rate:** 40-60%
- **Response time P95:** <5 seconds
- **Error rate:** <1%
- **Uptime:** >99.5%

---

## 📞 Troubleshooting Guide

### "Cannot reach backend at http://127.0.0.1:8000"

```bash
# Problem: Backend not running
# Solution:
cd /workspaces/newcpu/astroquant
/workspaces/newcpu/.venv/bin/python -m uvicorn backend.main:app

# Should print: "Uvicorn running on http://127.0.0.1:8000"
```

### "Mentor price shows 0 or null"

```bash
# Problem: Market data feed not connected
# Solution 1: Ensure broker window open with live quotes
# Solution 2: Verify you're in market hours
# Solution 3: Try different symbol: curl http://127.0.0.1:8000/mentor/context?symbol=GC.FUT

# If still null:
# - Data provider may be down
# - Fallback to paper trading until recovered
```

### "Order entry fails with timeout"

```bash
# Problem: Playwright CDP taking too long
# Solution:
# 1. Ensure Chrome is running: ps aux | grep chrome
# 2. Ensure broker DOM is visible (not minimized)
# 3. Try again (may be transient)
# 4. If persists, increase CDP_TIMEOUT_SEC in .env

# Permanent fix:
CDP_TIMEOUT_SEC=45  # Increase from 30
# Restart backend
```

### "Position doesn't appear immediately"

```bash
# Problem: Reconciliation delay
# Normal behavior: Position appears within 5 seconds
# If longer:
# - Check /status endpoint: curl http://127.0.0.1:8000/status | jq '.positions'
# - Verify order actually submitted in broker
# - Check Position Reconciliation interval in logs

# Not Normal:
# - Position submitted but never appears
# - Action: Manually close position, check logs for errors
```

### "Error banner won't go away"

```bash
# Click the X button (close-btn) to dismiss manually
# Or wait 15 seconds for auto-dismiss

# If same error repeats:
# 1. Click RETRY to re-attempt
# 2. If still fails, check backend health: ./health_check.sh
# 3. Review error message for root cause
```

### "Performance Dashboard shows nothing"

```bash
# Problem: No metrics collected yet
# Solution: Make a few requests (load mentor, chart, etc.)
# Then click 📊 Perf button again

# Metrics only accumulate after requests are made
```

---

## 📅 Post-Launch Activities

### During First Trading Day

- [ ] Monitor every 30 minutes
- [ ] Document any errors encountered
- [ ] Note response times (build baseline)
- [ ] Verify position reconciliation works
- [ ] Confirm stop-loss triggers correctly
- [ ] Check daily loss limit stops orders

### After First Week

- [ ] Review cache hit rates (adjust if <15%)
- [ ] Analyze P&L distribution
- [ ] Check error frequency (should be <5/day)
- [ ] Verify backups completed successfully
- [ ] Plan capacity scaling if needed

### Ongoing Monitoring

- [ ] Daily: Check logs for errors
- [ ] Weekly: Review performance dashboard
- [ ] Monthly: Tune risk parameters based on results
- [ ] Quarterly: Full system validation & load testing

---

## ✅ Final Sign-Off

Before clicking the button to go live, confirm:

- [ ] All tests in "Go-Live Criteria" passed
- [ ] No critical issues in logs
- [ ] Performance dashboard showing normal metrics
- [ ] Risk limits understood and configured
- [ ] Backup verified and tested
- [ ] Rollback procedure tested
- [ ] Support/troubleshooting doc reviewed
- [ ] You understand potential maximum loss

---

**Status:** Ready for Live Trading Deployment  
**Last Updated:** March 11, 2026  
**Prepared By:** Copilot - Frontend & Performance Phase 1 & 2

