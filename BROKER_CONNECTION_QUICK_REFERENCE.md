# QUICK REFERENCE: Broker Connection Status - v20260342

## 🔴 → 🟢 Connection Status Flow

```
BEFORE                          AFTER CLICKING "Open Broker"
═══════════════════════════════════════════════════════════════

🔴 Broker NOT Connected         🟢 Broker CONNECTED
❌ Bridge Ready: NO      →       ✅ Bridge Ready: YES
❌ Same Browser Mode: NO →       ✅ Same Browser Mode: YES  
❌ Broker Tabs: 0        →       ✅ Broker Tabs: 1
✅ Dashboard Tabs: 1     →       ✅ Dashboard Tabs: 1

Result: You can now trade! ✅
```

---

## 📍 WHERE TO FIND THINGS

### Execution & Feed Section (Right Panel)
```
┌─────────────────────────────────────────┐
│ Operations Console (right side panel)   │
├─────────────────────────────────────────┤
│ Execution & Feed                        │
│                                         │
│ ⚫ Playwright Connected    → YES         │
│ ⚫ Browser Heartbeat       → (time)      │
│ 🔴 Bridge Ready            → NO         │ ← Problem indicator
│ 🔴 Same Browser Mode       → NO         │ ← Problem indicator
│ ⚫ CDP Reachable           → YES         │
│ 🔴 Broker Tabs             → 0          │ ← Problem indicator
│ ⚫ Dashboard Tabs           → 1          │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ 🌐 Open Broker                      │ │ ← CLICK THIS!
│ │ ↻ Reconnect                         │ │
│ │ 🔗 Recover Bridge                   │ │
│ └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
```

### Offset & Quality Section (Also Right Panel)
```
┌─────────────────────────────────────────┐
│ Offset & Quality                        │
├─────────────────────────────────────────┤
│ Market Symbol          → XAUUSD         │
│ Broker Symbol          → GCZ26          │
│ Broker XAUUSD Price    → 2050.45        │ ← Prices from Maven
│ System Price           → 2050.40        │ ← Our calculation
│ Offset Difference      → 0.05 pts       │ ← Difference
│ Basis Status           → LIVE           │
│ Quality Score          → 85.2%          │
│ Hard Block             → NO             │
└─────────────────────────────────────────┘
```

### Multi-Symbol Table (Top of Operations)
```
┌────────────────────────────────────────────────────────────┐
│ Symbol    Conf  Phase  Basis  Broker Price  System Price   │
├────────────────────────────────────────────────────────────┤
│ XAUUSD    82%   BULL   LIVE   2050.45       2050.40        │
│ NQ        76%   BULL   LIVE   18500.25      18500.20       │
│ EURUSD    68%   BEAR   LIVE   1.0950        1.0948         │
└────────────────────────────────────────────────────────────┘
       Scroll right to see: Offset Diff column
```

### Iceberg/Absorption Data (Left Side or Floating)
```
┌─────────────────────────────────┐
│ Orderflow Summary               │
├─────────────────────────────────┤
│ Regime        → BULLISH         │
│ Alert Level   → HIGH            │
│ Iceberg Count → 3               │ ← Absorption detected!
│ Absorption    → 🟢 BULLISH      │ ← Direction (colored)
│ Signal Strength → 85%           │
│ Buy Aggression → 62%            │
│ Sell Aggression → 38%           │
│ Delta         → +450            │
└─────────────────────────────────┘
```

---

## 🎯 3-STEP SETUP PROCESS

```
STEP 1: Open Dashboard
┌─────────────────────────────────────────┐
│ Browser URL:                            │
│ http://127.0.0.1:8001/frontend/?v=aq-v20260342
│                                         │
│ Expected: Page loads in 2-3 seconds     │
│ ✅ Chart visible on left                │
│ ✅ Operations panel on right             │
│ ✅ Green "Open Broker" button visible   │
└─────────────────────────────────────────┘

STEP 2: Click "Open Broker" Button
┌─────────────────────────────────────────┐
│ Location: Right panel → Execution & Feed│
│ Button: 🌐 Open Broker (green)          │
│ Action: Click it                        │
│                                         │
│ What happens:                           │
│ 1. Fetches broker URL from backend      │
│ 2. Opens Maven in NEW browser tab       │
│ 3. Maven page starts loading            │
│ 4. Auto-detects Maven tab               │
│ 5. Connects Playwright bridge           │
└─────────────────────────────────────────┘

STEP 3: Verify Bridge is Ready
┌─────────────────────────────────────────┐
│ Timeline:                               │
│ • Immediately:                          │
│   🟠 Bridge Ready: NO (still loading)   │
│                                         │
│ • After 5 seconds:                      │
│   🟡 Bridge Ready: CHECKING...          │
│                                         │
│ • After Maven fully loads:              │
│   🟢 Bridge Ready: YES ← SUCCESS!       │
│                                         │
│ What to check:                          │
│ ✅ Bridge Ready: YES                    │
│ ✅ Same Browser Mode: YES               │
│ ✅ Broker Tabs: 1                       │
│ ✅ Broker XAUUSD Price: 2050.45         │
│ ✅ Iceberg Count: 3+ (or updates)       │
└─────────────────────────────────────────┘
```

---

## 🚨 QUICK FIXES

### Problem: Bridge Still Shows "NO"
```
Fix #1: Refresh Dashboard
  → Press F5 to reload page
  → Wait 2 seconds
  → Check Bridge Ready again

Fix #2: Click "Recover Bridge"
  → Located next to "Open Broker" button
  → Click gray "🔗 Recover Bridge" button
  → Wait 2-5 seconds
  → Should show YES now

Fix #3: Check Maven Tab
  → Click Maven browser tab
  → If showing "Just a moment...", wait
  → If showing Cloudflare challenge, solve it
  → Return to dashboard, click Recover Bridge
```

### Problem: Broker Tabs Still Shows "0"
```
Solution: Click "Open Broker" Again
  → Green 🌐 button may have had popup blocked
  → Check browser popup notifications
  → Allow popups for 127.0.0.1 domain
  → Click "Open Broker" button again
  → Maven tab should open
```

### Problem: Buy/Sell Prices Show "--"
```
Solution: Reconnect Browser
  → Click ↻ "Reconnect" button
  → Waits 1-2 seconds
  → Re-probes Maven selectors
  → Should find buy/sell buttons
  → Prices should populate
```

---

## ✅ SUCCESS CHECKLIST

When everything is working, you should see:

```
EXECUTION & FEED Section:
  ✅ Playwright Connected: YES
  ✅ Browser Heartbeat: (recent timestamp like "1s ago")
  ✅ Bridge Ready: YES ← Key indicator
  ✅ Same Browser Mode: YES ← Key indicator  
  ✅ CDP Reachable: YES
  ✅ Broker Tabs: 1
  ✅ Dashboard Tabs: 1

OFFSET & QUALITY Section:
  ✅ Basis Status: LIVE (not STALE/ERROR)
  ✅ Offset Status: OK (not HALT/ERROR)
  ✅ Broker XAUUSD Price: (number, not "--")
  ✅ Quality Score: > 60 (preferably > 80)

BROWSER TABS:
  ✅ Dashboard tab open: http://127.0.0.1:8001/frontend/?v=aq-v20260342
  ✅ Maven tab open: https://manager.maven.markets/app/trade
  ✅ Both in SAME Chrome window
  ✅ Can switch between tabs freely

CHART & SUMMARY:
  ✅ Chart showing candlesticks with no errors
  ✅ Iceberg Count > 0
  ✅ Absorption showing color (BULLISH/BEARISH/NEUTRAL)
  ✅ No red error messages in console

RESULT: ✅ SYSTEM READY FOR TRADING
```

---

## 🔍 WHAT EACH TABLE/PANEL SHOWS

| Component | Location | What It Shows | Key Fields |
|-----------|----------|---------------|-----------|
| **Execution & Feed** | Right panel top | Browser connection status | Bridge Ready, Tabs count |
| **Offset & Quality** | Right panel middle | Price calculations & quality | Broker Price, Offset, Basis |
| **Multi-Symbol Matrix** | Right panel top | All symbols status | Broker Price, System Price, Offset Diff |
| **Order Flow Summary** | Left or floating | Orderflow metrics | Iceberg Count, Absorption direction |
| **Chart Summary** | Left of chart | Real-time summary | Signal Strength, Confidence |

---

## 📊 ABSORPTION GUIDE

When you see "Iceberg Count: 3" and "Absorption: BULLISH":

```
What it means:
├─ 3 large orders detected being absorbed (hidden)
├─ 🟢 BULLISH color = being absorbed on BID side
├─ Interpretation: Smart money BUYING (hidden demand)
├─ Trading implication: Bullish signal ⬆️

vs

If "Absorption: BEARISH":
├─ 🔴 BEARISH color = being absorbed on ASK side
├─ Interpretation: Smart money SELLING (hidden supply)
├─ Trading implication: Bearish signal ⬇️
```

---

## 🆘 TROUBLESHOOTING MATRIX

| Issue | Quick Fix | Time |
|-------|-----------|------|
| Bridge Ready = NO | Click "Recover Bridge" | 2-5s |
| Broker Tabs = 0 | Click "Open Broker" | 5-10s |
| Prices show "--" | Click "Reconnect" | 1-2s |
| Iceberg Count = 0 | Wait for market data | 5-30s |
| Order panel not found | Click "Reconnect" | 1-2s |
| Overall frozen | Refresh (F5) | 2-3s |

---

## 🔗 IMPORTANT URLS

```
Dashboard:     http://127.0.0.1:8001/frontend/?v=aq-v20260342
Backend API:   http://localhost:8000
Broker Config: http://localhost:8000/status/broker_config
Bridge Status: http://localhost:8000/status/broker_bridge
Execution:     http://localhost:8000/status/execution
Market Data:   http://localhost:8000/market/orderflow_summary?symbol=XAUUSD
```

---

## 📝 DOCUMENTATION

- **Detailed UI Guide**: BROKER_CONNECTION_UI_GUIDE.md
- **Implementation Details**: BROKER_CONNECTION_IMPLEMENTATION.md
- **Full Validation Checklist**: FRONTEND_VALIDATION_CHECKLIST.md
- **Testing Summary**: FRONTEND_TESTING_SUMMARY.md

---

**Version**: v20260342  
**Last Updated**: 2026-03-25  
**Status**: ✅ READY FOR BROWSER TEST
