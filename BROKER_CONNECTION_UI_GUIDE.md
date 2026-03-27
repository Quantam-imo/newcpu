# Frontend Broker Connection UI Guide
**Version**: v20260342  
**Date**: March 25, 2026

---

## 🟢 NEW FEATURE: "Open Broker" Button

### Location & Function
A new green button has been added to the **Execution & Feed** section in the Operations panel:

```
┌─────────────────────────────────────────────────────────────────┐
│ Execution & Feed                                                │
├─────────────────────────────────────────────────────────────────┤
│ Playwright Connected         → YES                              │
│ Browser Heartbeat            → (timestamp)                      │
│ Bridge Ready                 → NO (until you click Open Broker) │
│ Same Browser Mode            → NO                               │
│ CDP Reachable                → YES                              │
│ Broker Tabs                  → 0 (until you open it)            │
│ Dashboard Tabs               → 1                                │
├─────────────────────────────────────────────────────────────────┤
│ 🌐 Open Broker    ↻ Reconnect    🔗 Recover Bridge              │  ← NEW ROW
├─────────────────────────────────────────────────────────────────┤
│ (rest of the fields)                                            │
└─────────────────────────────────────────────────────────────────┘
```

### What Happens When You Click "Open Broker"

1. **Click** the green 🌐 **Open Broker** button
2. **Fetches** the broker URL from backend: `https://manager.maven.markets/app/trade`
3. **Opens** Maven in a NEW tab (not same page) 
4. **Chrome DevTools Bridge** automatically connects via Playwright CDP
5. **Bridge status AUTO-UPDATES**:
   - Broker Tabs: 0 → 1 ✅
   - Bridge Ready: NO → YES ✅
   - Same Browser Mode: NO → YES ✅
6. **You stay on dashboard tab** - can switch between tabs as needed

### Workflow: From Broker Not Connected → Bridge Ready

```
1. Dashboard loads at http://127.0.0.1:8001/frontend/?v=aq-v20260342
   ↓ (Bridge shows DISCONNECTED - no broker tab yet)
   
2. Click "🌐 Open Broker" button
   ↓ (Opens Maven in new tab)
   
3. Maven loads https://manager.maven.markets/app/trade
   ↓ (Playwright detects Maven tab automatically)
   
4. Return to dashboard tab
   ↓ (Refresh page F5 or wait 3 seconds)
   
5. Check Execution & Feed section:
   ✅ Bridge Ready: YES
   ✅ Same Browser Mode: YES
   ✅ Broker Tabs: 1
   ✅ Dashboard Tabs: 1
   ✅ Order Panel Ready: READY
```

---

## 📊 UI Components Grouped by Function

### 1️⃣ BROKER CONNECTION STATUS (Execution & Feed Section)

**Location**: Right side panel → Operations → Execution & Feed

```
Playwright Connected    → YES/NO      (Is Playwright script connected to Chrome?)
Browser Heartbeat       → Timestamp   (When did we last ping the browser?)
Bridge Ready            → YES/NO      (Are both Maven + Dashboard accessible?)
Same Browser Mode       → YES/NO      (Are they in THE SAME Chrome process?)
CDP Reachable           → YES/NO      (Can we reach Chrome's debug protocol?)
Broker Tabs             → Count       (How many Maven tabs are open?)
Dashboard Tabs          → Count       (How many Dashboard tabs are open?)
```

**Status Colors**:
- 🟢 Green (good): Connected, Recent heartbeat, YES, READY
- 🟡 Yellow (warn): Stale, Degraded, NO but trying
- 🔴 Red (bad): Failed, Disconnected, ERROR

### 2️⃣ ACTION BUTTONS (Bridge Management)

**Location**: Execution & Feed section, action button row

```
🌐 Open Broker
├─ Functionality: Opens Maven broker URL in new tab
├─ Result: Maven tab opens, Bridge auto-connects
├─ Used when: Bridge Shows "NO", need to initialize
└─ Does NOT navigate current page

↻ Reconnect
├─ Functionality: Restarts Playwright connection to Chrome
├─ Result: Reconnects to existing tabs
├─ Used when: "Playwright Connected" shows NO
└─ Useful after Chrome crashes/restarts

🔗 Recover Bridge
├─ Functionality: Force-probes all tabs, rebuilds bridge connection
├─ Result: Re-scans Chrome for Maven and Dashboard tabs
├─ Used when: "Bridge Ready" shows NO despite tablets being open
└─ Takes 2-5 seconds to complete
```

---

### 3️⃣ OFFSET & QUALITY PANEL

**Location**: Right side panel → Operations → Offset & Quality section

```
┌─────────────────────────────────────────────────────────────────┐
│ Offset & Quality                                                │
├─────────────────────────────────────────────────────────────────┤
│ Market Symbol           → E.g., XAUUSD (canonical form)         │
│ Futures Source          → E.g., GC.FUT (data source)            │
│ Broker Symbol           → E.g., GCZ26 (contract)                │
│ Basis Status            → LIVE / STALE / ERROR                  │
│ Offset Status           → OK / HALT / ERROR                     │
│ Offset Deviation        → 0.250 pts (difference)                │
│ Offset Difference       → -0.125 pts (futures - broker)         │
│ Broker XAUUSD Price     → 2050.45 (current bid/ask mid)         │
│ Broker Quote (Selected) → B 2050.40 | A 2050.50                 │
│ Quality Score           → 85.2 (0-100, higher better)           │
│ Quality Grade           → GOOD / FAIR / POOR                    │
│ Signal Candidates       → 3 (absorption events detected)        │
│ Hard Block              → NO (trading allowed) / YES (halted)   │
│ Broker Symbols (All)    → GC.FUT | NQ.FUT | 6E.FUT              │
│ Reasons                 → List of block reasons if any          │
└─────────────────────────────────────────────────────────────────┘
```

**Key Metrics Explained**:

| Field | Meaning | Good State |
|-------|---------|-----------|
| Basis Status | Market basis data sync | LIVE |
| Offset Status | Price offset calculation | OK |
| Offset Deviation | How far off the offset is | Small (< 1 pt) |
| Offset Difference | futures_price - broker_price | Negative (futures higher) |
| Quality Score | Confidence in trade signals | > 80 |
| Quality Grade | Overall quality ranking | GOOD |
| Hard Block | Circuit breaker status | NO |

---

### 4️⃣ BROKER PRICE TABLE (Multi-Symbol Matrix)

**Location**: Right side panel → Operations top section → scroll down to table

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ Symbol │ HTF │ LTF │ Model │ Conf │ Risk% │ Phase │ Mode │ Basis │ Resolver │ Watch │ ...
├──────────────────────────────────────────────────────────────────────────────────────┤
│ XAUUSD │  ↑  │  ↓  │  BUY  │ 82% │  2.1  │ BULL  │ FAST │ LIVE  │ RESOLVED │  NO  │ ...
│ NQ     │  ↑  │  ↑  │  BUY  │ 76% │  1.8  │ BULL  │ LIVE │ LIVE  │ RESOLVED │  NO  │ ...
│ EURUSD │  ↓  │  ↓  │ SELL  │ 68% │  1.5  │ BEAR  │ LIVE │ LIVE  │ RESOLVED │  NO  │ ...
└──────────────────────────────────────────────────────────────────────────────────────┘

[Scroll Right →] shows:
... News │ Broker Price  │ System Price  │ Offset Diff │
... HALT │    2050.45    │    2050.40    │    0.05     │ (broker higher)
... NORM │    18500.25   │    18500.20   │    0.05     │
... NORM │    1.0950     │    1.0948     │    0.0002   │
```

**Column Meanings**:

| Column | Meaning |
|--------|---------|
| **Symbol** | Trading symbol (XAUUSD, NQ, EURUSD) |
| **HTF** | Higher timeframe trend (↑ up, ↓ down) |
| **LTF** | Lower timeframe trend |
| **Model** | AI model signal (BUY/SELL/HOLD) |
| **Conf** | Confidence % (0-100) |
| **Risk%** | Daily risk as % of account |
| **Phase** | Market phase (BULL/BEAR/NEUTRAL) |
| **Mode** | Data mode (LIVE/FAST_FALLBACK/CACHED) |
| **Basis** | Basis engine status (LIVE/STALE) |
| **Resolver** | Symbol resolution status (RESOLVED/UNKNOWN) |
| **Watch** | Is this symbol watch-only? |
| **News** | News state (NORMAL/HALT/BREAKOUT) |
| **Broker Price** | Current bid/ask mid from Maven UI |
| **System Price** | Calculated price in our system |
| **Offset Diff** | Difference between them (should be small) |

---

### 5️⃣ BUY/SELL BUTTON PRICES

**Location**: Execution & Feed section, Order Panel fields

```
Order Panel Ready     → READY / MISSING
Buy Button Price      → 2050.45 (price to execute BUY orders)
Sell Button Price     → 2050.50 (price to execute SELL orders)
```

**What This Means**:
- These prices are captured from the Maven UI buy/sell buttons
- System uses these to place actual trades
- If showing "--", the order panel is not visible on Maven page

---

### 6️⃣ ABSORPTION & ICEBERG DATA (Orderflow Summary)

**Location**: Left side of chart → Summary panel (or open "OF Summary" micro-panel)

```
┌─────────────────────────────────────────────────────────────────┐
│ Orderflow Summary                                               │
├─────────────────────────────────────────────────────────────────┤
│ Regime           → BULLISH (dominant direction from orderflow) │
│ Alert Level      → HIGH (strong signal) / MEDIUM / LOW         │
│ Signal Strength  → 85.2% (confidence)                          │
│ Buy Aggression   → 62% (aggressive buys in orderflow)          │
│ Sell Aggression  → 38% (aggressive sells in orderflow)         │
│ Delta            → +450 (net aggressive volume bought)         │
│ Cumulative Delta → +1230 (running sum)                         │
│ Imbalance        → BUY (more aggressive buys than sells)       │
│ DOM Spread       → 0.05 (bid-ask spread)                       │
│ Iceberg Count    → 3 (absorption events detected) ← Key!       │
│ Absorption       → BULLISH (colored indicator) ← Key!          │
│ Confidence       → 87.3% (backend confidence in calc)          │
│ Narrative        → "Orderflow XAUUSD: BULLISH, absorption=3..." │
└─────────────────────────────────────────────────────────────────┘
```

**Iceberg Count Meaning**:
- **0** = No absorption detected, normal orderflow
- **1-3** = Light absorption, some large orders being hidden
- **4+** = Heavy absorption, sophisticated traders active

**Absorption Direction**:
- 🟢 **BULLISH** (green) = Absorption happening on bid side (buyers)
- 🔴 **BEARISH** (red) = Absorption happening on ask side (sellers)  
- ⚪ **NEUTRAL** (gray) = No clear absorption bias

---

## 🔄 Bridge Connection Flow

### Happy Path (Everything Works)

```
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Dashboard Loads                                         │
│ http://127.0.0.1:8001/frontend/?v=aq-v20260342                  │
│                                                                 │
│ Result:                                                         │
│   ✅ Playwright Connected: YES                                 │
│   ❌ Bridge Ready: NO (no Maven tab yet)                        │
│   ❌ Same Browser Mode: NO                                      │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: Click "🌐 Open Broker" Button                           │
│                                                                 │
│ Action:                                                         │
│   1. Fetch broker_config endpoint: /status/broker_config        │
│   2. Get Maven URL: https://manager.maven.markets/app/trade     │
│   3. window.open(url, "maven_broker")                           │
│   4. New TAB opens with Maven                                   │
│                                                                 │
│ Result:                                                         │
│   ✅ Playwright Connected: YES                                 │
│   ❓ Bridge Ready: Checking...                                  │
│   ❌ Broker Tabs: 0 → 1 (Maven tab detected)                    │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Maven Page Loads (show may take 5-10 secs)              │
│                                                                 │
│ Backend Action (automatic):                                     │
│   1. Playwright connects_to_broker()                            │
│   2. Connects to Maven tab via CDP                              │
│   3. Captures quote snapshot (bid/ask)                          │
│   4. Captures order panel position                              │
│                                                                 │
│ Result:                                                         │
│   ✅ Playwright Connected: YES                                 │
│   ✅ Quote Available: mid=2050.45                               │
│   ✅ Order Panel Ready: READY                                  │
│   ✅ Bridge Ready: YES ← SUCCESS!                              │
│   ✅ Same Browser Mode: YES                                    │
│   ✅ Broker Tabs: 1                                             │
│   ✅ Dashboard Tabs: 1                                          │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: System Ready for Trading                                │
│                                                                 │
│ Features enabled:                                               │
│   ✅ Can read symbols from Maven                                │
│   ✅ Can read quote prices (bid/ask)                            │
│   ✅ Can detect order panel buttons                             │
│   ✅ Can click buy/sell buttons                                 │
│   ✅ Can verify risk controls                                   │
│                                                                 │
│ Iceberg detection active:                                       │
│   ✅ Orderflow summary showing absorption                       │
│   ✅ Iceberg count updating in real-time                        │
│   ✅ Absorption direction (BULLISH/BEARISH) displayed           │
└─────────────────────────────────────────────────────────────────┘
```

---

## ⚠️ Troubleshooting

### Issue: Bridge Ready shows NO

**Cause**: Maven page not fully loaded yet  
**Fix**:
1. Wait 5 seconds for Maven to load
2. Check Maven tab - should show trading interface (not "Just a moment...")
3. Click "🔗 Recover Bridge" button
4. Refresh dashboard (F5)

### Issue: Broker Tabs shows 0

**Cause**: Maven tab hasn't been opened yet  
**Fix**:
1. Click "🌐 Open Broker" button
2. Confirm Maven opens in NEW tab
3. Go back to dashboard tab
4. Should now show Broker Tabs: 1

### Issue: Clicking "Open Broker" does nothing

**Cause**: Popup blocker may be preventing new tab  
**Fix**:
1. Check browser popup blocker settings
2. Allow popups for this domain (127.0.0.1:8001)
3. Try clicking button again
4. Alternatively, manually open Maven at: `https://manager.maven.markets/app/trade`

### Issue: Maven shows "Just a moment..." / Cloudflare Challenge

**Cause**: Browser login not complete  
**Fix**:
1. Go to Maven tab
2. Wait for page to fully load
3. Complete Cloudflare challenge if prompted
4. Return to dashboard tab
5. Click "🔗 Recover Bridge"
6. Bridge should now show YES

### Issue: Quote showing but Buy/Sell prices show "--"

**Cause**: Order panel buttons not detected on Maven UI  
**Fix**:
1. Go to Maven tab
2. Verify you can see BUY and SELL buttons on-screen
3. Return to dashboard
4. Click "↻ Reconnect" button
5. Selectors will re-probe and should find buttons

---

## 🎯 Quick Start

### To Get Bridge Ready in 30 Seconds:

1. **Open Dashboard**: `http://127.0.0.1:8001/frontend/?v=aq-v20260342`
2. **Wait 2 seconds** for page to load
3. **Look for**: "Execution & Feed" section on right side
4. **Click**: Green **🌐 Open Broker** button
5. **Go back** to dashboard tab (browser tabs may switch)
6. **Check**: Bridge Ready should now show YES
7. **Done!** ✅

### If Bridge Still Shows NO:

1. Check Maven tab - is it fully loaded? (not showing "Just a moment...")
2. Click **🔗 Recover Bridge** button
3. Wait 2-3 seconds
4. Refresh dashboard (F5)
5. Check again - should be YES

---

## 📋 Expected Displays

### When Everything Works ✅

```text
Execution & Feed Section:
  Playwright Connected    ✅ YES
  Browser Heartbeat       ✅ 2026-03-25 01:15:42 (1s)
  Bridge Ready            ✅ YES
  Same Browser Mode       ✅ YES
  CDP Reachable           ✅ YES
  Broker Tabs             ✅ 1
  Dashboard Tabs          ✅ 1
  
Offset & Quality:
  Basis Status            ✅ LIVE
  Offset Status           ✅ OK
  Offset Deviation        ✅ 0.250 pts
  Broker XAUUSD Price     ✅ 2050.45
  Quality Score           ✅ 85.2
  Hard Block              ✅ NO

Order Flow Summary:
  Iceberg Count           ✅3 (BULLISH)
  Absorption              ✅ BULLISH
  Signal Strength         ✅ 85%
```

### When Broker Not Opened ❌

```text
Execution & Feed Section:
  Playwright Connected    ✅ YES
  Browser Heartbeat       ✅ Recent
  Bridge Ready            ❌ NO
  Same Browser Mode       ❌ NO
  Broker Tabs             ❌ 0
  Dashboard Tabs          ✅ 1
  
↓ CLICK "🌐 Open Broker" BUTTON TO FIX ↓
```

---

## 🔑 Key Takeaways

1. **"Open Broker" button** is the ONE-CLICK fix to connect Maven
2. **Bridge Ready = YES** means system can read prices and execute trades
3. **Broker Tabs must be 1** (one Maven window open)
4. **Dashboard Tabs must be 1** (one AstroQuant window open)
5. **Both must be in SAME Chrome window** (not separate windows)
6. **Offset table** shows price diffs and quality metrics
7. **Iceberg Count** indicates hidden order absorption activity
8. **Absorption BULLISH/BEARISH** shows directional bias of large orders

---

**Version**: v20260342  
**Updated**: 2026-03-25  
**Status**: ✅ READY FOR TESTING
