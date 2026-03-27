# AstroQuant Frontend Validation Checklist

**Date**: March 25, 2026  
**System Status**: Backend RUNNING, Chrome Remote Debug RUNNING, Orchestrator RUNNING

## Current System State

### Backend Status - Backend Endpoints ✅
```
✓ Broker Status: CONNECTED (latency: 12ms, Account: SIM-123456)
✓ System Health: OK
  - CPU: 39.9%, Memory: 30.9%, Disk: 60%
  - Database: OK
  - Celery: RUNNING
  - Orchestrator: RUNNING
  - Data Feed: OK
```

### Broker Bridge Status - CDP Connection ⚠️
```
✓ Chrome CDP: Reachable (Chrome/146.0.7680.153)
✓ Broker Tab: Found (Maven, but Cloudflare Challenge detected)
⚠ Dashboard Tab: MISSING - "AstroQuant dashboard tab not open"
✗ Bridge Ready: NO (requires both Maven + Dashboard in same session)
✗ Same Browser Mode: NO (requires both tabs)
✗ Quote Available: NO
✗ Order Panel Ready: NO
```

**Key Finding**: The issue is that the frontend dashboard hasn't been opened yet in the same remote-debug Chrome session. This is why the bridge connection shows DEGRADED.

---

## Manual Validation Steps (Do This In Browser)

### Step 1: Open Frontend in Remote-Debug Chrome ✅ REQUIRED
**URL**: `http://127.0.0.1:8001/frontend/?v=aq-v20260341`

**Expected After Load**:
- Chart loads with candlestick data
- Ops panel visible on right side
- Summary panel shows orderflow metrics
- NO console errors about "Failed to execute json on Response" or CORS blocks

**To Do**:
1. Open a terminal/RDP into the dev container
2. Navigate to http://127.0.0.1:8001/frontend/?v=aq-v20260341
3. Keep this window open while testing

---

### Step 2: Check Broker Connection Display (Ops Panel > Execution & Feed)

**Panel Location**: Right side of screen, "Execution & Feed" section

**Fields to Validate**:

| Field | Expected | How to Check |
|-------|----------|-------------|
| Playwright Connected | YES | Should turn green after dashboard tab opens |
| Browser Heartbeat | Timestamp + age | Should show recent age (< 5 seconds) |
| Bridge Ready | YES | Should turn green when Maven + Dashboard in same Chrome |
| Same Browser Mode | YES | Should show YES when both tabs in same session |
| CDP Reachable | YES | Should show YES (Chrome debug protocol) |
| Broker Tabs | 1 | Count of Maven broker tabs open in Chrome |
| Dashboard Tabs | 1 | Count of AstroQuant dashboard tabs (should be 1 after Step 1) |
| Execution Status | CONNECTED | Order panel is ready to send orders |
| Order Panel Ready | READY | Buy/Sell buttons are visible and functional |

**Success Criteria**:
- All green status indicators
- Bridge Ready = YES
- Same Browser Mode = YES
- Both Broker Tabs and Dashboard Tabs count > 0

---

### Step 3: Check Broker Link Opening (Same-Page Navigation)

**Concept**: When you click "Open Broker" or the Maven link in the dashboard, it should:
1. ✅ Open in a NEW TAB (not same page)
2. ✅ Automatically connect via Playwright's CDP bridge
3. ✅ Update the Bridge status to READY once the page loads

**To Test**:
1. In the dashboard, look for a "Broker Link" or "Open Maven" button
2. Click it
3. Should open new tab with Maven broker
4. Return to dashboard tab
5. Check Ops Panel: "Dashboard Tabs" count should still be 1, "Broker Tabs" should show 1+
6. Refresh the dashboard (F5)
7. Check Ops Panel: "Bridge Ready" should now show YES ✅

**Success Criteria**:
- Clicking broker link opens Maven in NEW tab (not same page)
- Can switch between browser tabs
- Dashboard and Maven both remain open in Chrome remote debug
- Ops Panel shows "Bridge Ready = YES" ✅

---

### Step 4: Check Playwright Connection

**Indication**: "Playwright Connected" field in Ops Panel

**What it means**:
- Playwright process is actively connected to Chrome remote debug session
- Heartbeat timestamp is recent (< 10 seconds old)
- Page object is available for querying

**To Verify**:
1. Look at "Playwright Connected" in Ops Panel - should show YES
2. Look at "Browser Heartbeat" - should show current timestamp and age
   - Green if age < 5 seconds
   - Yellow if 5-15 seconds
   - Red if > 15 seconds
3. Open DevTools on Maven tab (F12)
4. Check console - should see Playwright browser automation messages
5. Try to execute a trade - order execution should work if Playwright is connected

---

### Step 5: Check Bridge Connection Display

**Location**: Ops Panel > "Execution & Feed" section

**Fields**:
- Bridge Ready: YES/NO
- Same Browser Mode: YES/NO
- CDP Reachable: YES/NO
- Quote Available: (from quote snapshot)
- Order Panel Ready: READY/MISSING

**Recovery if Bridge is NOT Ready**:
1. Ensure BOTH Maven AND Dashboard tabs are open in the SAME Chrome remote debug window
2. Click the button "Bridge Ready Recovery" if available (searches for missing tabs)
3. Refresh dashboard page: press F5
4. Wait 3 seconds
5. Check Bridge status again - should transition to YES

**If still not ready**:
- Run Deep Probe: Click "Deep Probe All" button in Ops Panel
- This will probe all configured symbols and rebuild the symbol resolver
- Should take 5-30 seconds depending on network/broker

---

### Step 6: Check Broker Symbol Absorption & Price Calculation

**Symbol Absorption** = System automatically detecting and handling broker symbol format conversions for price calculations

**Location**: 
1. Chart Summary Panel (left side of chart)
   - Field: "Iceberg Count" - count of detected absorption events
   - Field: "Absorption" - BULLISH/BEARISH/NEUTRAL colored indicator
2. Orderflow Summary Micro Panel
   - Same fields showing real-time absorption metrics

**How to Verify Absorption is Working**:

1. **Open the chart** for XAUUSD (gold)
2. **Watch the summary panel** on the left:
   ```
   Iceberg Count: 3          (shows number of absorption events)
   Absorption: BULLISH       (colored: green=bullish, red=bearish, gray=neutral)
   ```
3. **Meaning**:
   - Iceberg Count: Number of large orders being absorbed (hidden) into market
   - Absorption Type: If bullish absorption happening, expect price to go up
4. **Verify Symbol Resolver** is working:
   - Look at Ops Panel > "Basis & Resolver" section
   - Field: "Resolver Active" - should show active symbol (e.g., "XAUUSD", "GCZ26")
   - Field: "Resolver Status" - should show "RESOLVED" or "OK"
   - Field: "Resolver TTL" - time until resolver expires (should be > 0 seconds)

**What happens with Symbol Absorption**:
1. System receives price quote from broker in broker's symbol format (e.g., "GCZ26")
2. Symbol Resolver converts to canonical form (e.g., "XAUUSD")
3. System calculates absorption levels based on orderflow
4. System absorbs these symbols into its internal price calculation
5. Display shows Iceberg Count and Absorption direction

**Success Criteria**:
- Iceberg Count shows non-zero when absorbing orders
- Absorption shows BULLISH/BEARISH aligned with market direction
- Resolver Active shows the active symbol being tracked
- Resolver Status shows RESOLVED (not UNKNOWN or ERROR)
- Price updates flowing to chart in real-time

---

## Verification Commands (From Terminal)

### Check Backend Health
```bash
curl http://localhost:8000/status | jq .broker_status
# Expected: connected: true, status: CONNECTED
```

### Check Broker Bridge Status
```bash
curl http://localhost:8000/status/broker_bridge | jq .
# Expected: bridge_ready: true, same_browser_mode: true
```

### Check Execution Status
```bash
curl http://localhost:8000/status/execution | jq .
# Expected: execution_status: CONNECTED, healthy: true
```

### Check Symbol Resolver for Specific Symbol
```bash
curl "http://localhost:8000/market/symbol_resolver?symbol=XAUUSD" | jq .
# Expected: active_symbol shows resolved symbol, status: RESOLVED
```

### Test Market Data Flow
```bash
curl "http://localhost:8000/market/orderflow_summary?symbol=XAUUSD" | jq .summary
# Expected: iceberg_count > 0, absorption shows BULLISH/BEARISH/NEUTRAL
```

---

## Expected Behavior Summary

### ✅ When Everything Works
```
Dashboard Open
  ↓
Playwright connects to Chrome CDP
  ↓
Both Maven + Dashboard in same session detected
  ↓
Bridge Ready = YES
  ↓
Quote snapshot obtained from Maven UI (bid/ask)
  ↓
Order Panel snapshot obtained (button placement, pricing)
  ↓
Symbol Resolver converts broker symbols → canonical symbols
  ↓
Absorption calculations flowing
  ↓
Chart rendering with Iceberg data
  ↓
All Ops Panel fields populated ✅
```

---

## Troubleshooting

### Issue: Dashboard Tab Count = 0
**Cause**: Frontend not opened in same Chrome session  
**Fix**: Open `http://127.0.0.1:8001/frontend/?v=aq-v20260341` in the SAME remote-debug Chrome window (not separate window)

### Issue: Bridge Ready = NO even with both tabs open
**Cause**: Quote snapshot failing (broker page may be on login screen, Cloudflare challenge, or selector issue)  
**Fix**:
1. Check Maven tab - if showing "Just a moment..." or Cloudflare challenge, complete it
2. Click "Bridge Ready Recovery" button
3. Run Deep Probe to recalibrate selectors
4. Refresh dashboard (F5)

### Issue: Playwright Connected = NO
**Cause**: Chrome CDP connection failed or heartbeat timed out  
**Fix**:
1. Verify Chrome is running: `ps aux | grep chrome`
2. Test CDP: `curl http://127.0.0.1:9222/json/version`
3. If no response, restart Chrome: `bash /workspaces/newcpu/start_chrome_remote_debug.sh`
4. Refresh dashboard

### Issue: Iceberg Count = 0 / Absorption = NEUTRAL
**Cause**: No absorption events in current market window or data not flowing  
**Fix**:
1. Verify feed is connected: Check "Feed" status in Ops Panel
2. Run Deep Probe All to probe symbols
3. Check symbol resolver: "Resolver Status" should be RESOLVED
4. If symbol not resolving: May need to manually add to symbol registry

### Issue: "Failed to execute 'json' on 'Response': body stream already read"
**Cause**: This was fixed in v20260341 - Should NOT see this anymore  
**Fix**: If still seeing: Hard refresh browser (Ctrl+Shift+R) to load new JavaScript

---

## Next Steps After Validation

1. ✅ Verify all connection displays are populated
2. ✅ Confirm broker link opens correctly (NEW tab, not same page)
3. ✅ Validate symbol absorption flowing to price calculations
4. ✅ Test that chart renders with iceberg overlay data
5. ⏳ Run a test trade to confirm order execution works
6. ⏳ Monitor Iceberg detection and Absorption calculations over time
7. ⏳ Check that symbol resolver handles multiple symbols correctly

---

## Reference: UI Component IDs

For frontend debugging in browser console:

```javascript
// Playwright Status
document.getElementById("opsPlaywrightConnected").textContent

// Bridge Status
document.getElementById("opsBridgeReady").textContent
document.getElementById("opsSameBrowserMode").textContent

// Tab Counts
document.getElementById("opsBrokerTabs").textContent
document.getElementById("opsDashboardTabs").textContent

// Symbol Absorption
document.getElementById("summaryIceberg").textContent
document.getElementById("summaryAbsorption").textContent

// Resolver Status
document.getElementById("resolverActive").textContent
document.getElementById("resolverStatus").textContent
```

---

**Last Updated**: 2026-03-25 @ 01:06 UTC  
**System Ready**: YES ✅  
**Frontend Test**: PENDING  
