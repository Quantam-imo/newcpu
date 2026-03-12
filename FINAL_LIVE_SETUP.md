# 🚀 AstroQuant Live Trading - Final Setup & Launch Guide

This document provides complete instructions to move AstroQuant to live CPU production trading with Chrome debugging setup.

**Status**: ✅ **Project Ready for Live Trading**

---

## 📋 Quick Start (5 minutes)

### Step 1: Launch with One Command

```bash
cd /workspaces/newcpu
bash LIVE_LAUNCH.sh
```

This script will:
- ✅ Configure environment for live trading
- ✅ Launch Chrome with remote debugging enabled
- ✅ Start FastAPI backend
- ✅ Calibrate selector profiles
- ✅ Run final health checks

### Step 2: Complete Browser Login

1. Chrome window will open automatically showing broker login
2. Complete any **Cloudflare challenge** (click "Verify")
3. Log into your **MatchTrader** account
4. Ensure you see the **order entry form**
5. Return to terminal and press ENTER

### Step 3: Verify System

When prompted, the script will:
- Calibrate order entry selectors
- Run system health check
- Display live trading readiness status

### Step 4: Open Web Dashboard

```
http://127.0.0.1:8000
```

Start trading! Monitor signals, execute orders, verify positions.

---

## 🔧 Complete Setup Details

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                   AstroQuant Live System                    │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐        ┌──────────────┐                 │
│  │ FastAPI      │◄──────►│ Chrome       │                 │
│  │ Backend      │        │ Debugging    │                 │
│  │ (8000)       │        │ (CDP 9222)   │                 │
│  └──────────────┘        └──────────────┘                 │
│       │                         │                         │
│       │                         │                         │
│  ┌────▼──────┐  ┌──────────────▼──┐  ┌──────────────┐   │
│  │ Mentor     │  │  Playwright      │  │MatchTrader   │   │
│  │ Engine V3  │  │  Executor        │  │ Selector     │   │
│  │ (ICT, etc) │  │  (Auto-click)    │  │ Profiles     │   │
│  └────────────┘  └──────────────────┘  └──────────────┘   │
│       │                                                    │
│  ┌────▼──────────────────────────┐                       │
│  │  Databento Live Market Data   │                       │
│  │  (GC.c.1, NQ.c.1, etc)        │                       │
│  └─────────────────────────────────┘                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Component Status

| Component | Status | Details |
|-----------|--------|---------|
| **FastAPI Backend** | ✅ Running | Port 8000, live data feeds active |
| **Chrome CDP** | ⚙️ Manual | Requires login to broker |
| **Playwright** | ✅ Connected | Auto-attach to Chrome CDP |
| **Mentor AI** | ✅ Active | ICT, Iceberg, Institution, Gann signals |
| **Market Data** | ✅ Live | Databento GLBX.MDP3, 6 symbols |
| **Selector Profile** | ✅ Loaded | Runtime calibration ready |
| **Web Dashboard** | ✅ Ready | Real-time monitoring |

---

## 🔐 Environment Configuration

The `LIVE_LAUNCH.sh` script automatically configures `.env` with:

### Critical Settings

```env
# Chrome DevTools Protocol (CDP)
CDP_ENDPOINT=ws://127.0.0.1:9222
EXECUTION_BROWSER_CDP_URL=ws://127.0.0.1:9222
EXECUTION_BROWSER_AUTO_ATTACH=true
EXECUTION_BROWSER_TIMEOUT_MS=30000

# Order Execution
ORDER_EXECUTION_MODE=confirm-token      # Requires approval before each trade
ORDER_SYMBOL_LOCK=true                   # Prevents wrong symbol orders
ORDER_MICRO_LOT_SIZE=0.01                # Start with micro-lots

# Risk Management
DAILY_LOSS_LIMIT_USD=500
MAX_CONCURRENT_POSITIONS=3
DRAWDOWN_MAX_PERCENT=10
```

### Execution Modes

| Mode | Behavior | When to Use |
|------|----------|------------|
| `dry-run` | Log only, no trades | Initial testing |
| `confirm-token` | **RECOMMENDED** | Ask permission before each trade |
| `auto` | Auto-execute all signals | After validation only |

---

## 🎯 Step-by-Step Live Launch

### Phase 1: Initialize System

```bash
# Start fresh environment
cd /workspaces/newcpu
bash LIVE_LAUNCH.sh
```

What happens:
1. ✅ Backs up current `.env`
2. ✅ Creates production `.env` with CDP settings
3. ✅ Launches Chrome with `--remote-debugging-port=9222`
4. ✅ Starts FastAPI backend
5. ⏳ Waits for you to complete broker login

### Phase 2: Browser Setup (Manual Action)

**[Chrome opens automatically]**

1. **Handle Cloudflare Challenge** (if present)
   - Wait for "Just a moment..." page to load
   - Click "Verify" or solve challenge
   - Page redirects to broker

2. **Log Into Broker**
   - Username: Your MatchTrader account
   - Password: Your credentials
   - Two-factor auth (if enabled)

3. **Verify Page Load**
   - You should see trading dashboard
   - Order entry form visible
   - Chart display working

4. **Return to Terminal**
   - Press ENTER to continue

### Phase 3: Selector Calibration

```
Script will run selector calibration...
[Detecting order entry form elements]
[Mapping click targets for BUY/SELL/VOLUME]
[Saving to data/matchtrader_selectors.json]
✓ Calibration complete
```

### Phase 4: System Verification

```
Running health check...

[1/8] Backend Connectivity       ✓ PASS
[2/8] Frontend Load              ✓ PASS
[3/8] System Health              ✓ PASS
[4/8] Mentor Data                ✓ PASS
[5/8] Chart Data                 ✓ PASS
[6/8] Order Entry System         ✓ PASS
[7/8] Performance Cache          ✓ PASS
[8/8] File Integrity             ✓ PASS

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✓ ALL SYSTEMS NOMINAL - READY FOR LIVE TRADING!
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 💻 Opening Dashboard & Managing Trades

### Web Dashboard

```
URL: http://127.0.0.1:8000
```

#### Features:
- **Live Symbol Monitor**: Watch XAUUSD, NQ, EURUSD, BTC, US30
- **Mentor Signals**: ICT, Iceberg, Institution, Gann analysis
- **Order Panel**: Send Buy/Sell/Close orders
- **Position Tracker**: Real-time P&L, Equity, Drawdown
- **Chart View**: 1m/5m/15m/1h candles with overlays
- **Performance Dashboard**: Cache stats, API response times

### First Trade (Validation)

1. **Select Symbol**: XAUUSD (most liquid)
2. **Review Signals**: Check mentor data confidence
3. **Set Order Size**: 0.01 lot (micro-lot)
4. **Send Order**: Click BUY or SELL
5. **Confirm**: Approve in popup (confirm-token mode)
6. **Monitor**: Position appears in "Open Positions"
7. **Close**: Click CLOSE when ready to exit

### Live Data Feeds

**Databento GLBX.MDP3** provides:
- Tick-by-tick gold (GC.c.1) futures
- Nasdaq (NQ.c.1) continuous contracts
- EUR/USD (6E.c.1) forex futures
- Bitcoin (BTC.c.1) perpetuals
- S&P500 (ES.c.1) emini
- Indices (YM.c.1) Russell

**Fallback**: If Databento unavailable, mentor uses broker spot quotes

---

## 🔍 Monitoring & Debugging

### View Logs

```bash
# Backend API logs
tail -f logs/backend.log

# Chrome logs
tail -f logs/chrome.log

# Launch sequence
tail -f logs/live_launch.log
```

### Check System Status

```bash
# Full system status
curl http://127.0.0.1:8000/status | jq .

# Execution engine status
curl http://127.0.0.1:8000/status/execution | jq .

# Mentor data for symbol
curl http://127.0.0.1:8000/mentor/context?symbol=XAUUSD | jq .

# Chart candles
curl http://127.0.0.1:8000/chart/data?symbol=XAUUSD&timeframe=1m&limit=20 | jq .

# Dashboard multi-symbol
curl http://127.0.0.1:8000/dashboard/multi_symbol | jq .
```

### Browser Chrome DevTools

From Chrome:
1. Press `F12` to open DevTools
2. Go to **Sources** tab
3. Set breakpoints in order execution code
4. Monitor CDP protocol messages in **Network**

---

## ⚠️ Critical Decision Points

### Go Live Decision Checklist

Before changing to `ORDER_EXECUTION_MODE=auto`:

- [ ] Tested dry-run orders (no real trades)
- [ ] Executed at least 1 micro-lot live trade
- [ ] Verified position appears in trading account
- [ ] Confirmed positions reconcile (internal == broker)
- [ ] Checked P&L calculation is accurate
- [ ] Reviewed stop-loss and take-profit placement
- [ ] Confirmed no order slippage issues
- [ ] Validated order time is within market hours
- [ ] Checked news events nearby (no halts)
- [ ] Risk parameters are conservative (0.01 lot, small SL)

### Manual Trading (Initial Phase)

Recommended approach:
1. Set `ORDER_EXECUTION_MODE=confirm-token` (default)
2. Each order requires manual confirmation
3. Execute 5-10 trades successfully
4. Monitor fills and P&L
5. Build confidence
6. Then switch to `auto` if desired

---

## 🛡️ Safety & Risk Controls

### Hard Limits (Built-In)

| Limit | Value | Override |
|-------|-------|----------|
| **Daily Loss** | $500 | DAILY_LOSS_LIMIT_USD |
| **Max Positions** | 3 concurrent | MAX_CONCURRENT_POSITIONS |
| **Max Drawdown** | 10% | DRAWDOWN_MAX_PERCENT |
| **Micro Lot** | 0.01 | ORDER_MICRO_LOT_SIZE |

### Graceful Degradation

If execution fails:
- Order logged with error reason
- Broker position NOT created (fails safe)
- System continues running
- User can retry or adjust parameters

### Correlation Risk

Sistema monitors symbol correlation:
- Gold (GC) + Bonds often inverse
- NQ + ES often correlated
- EUR/USD + stocks diverge

Adjusts position sizing automatically via `CORRELATION_MULTIPLIER`

---

## 🔄 Daily Operations

### Morning Startup

```bash
cd /workspaces/newcpu
bash LIVE_LAUNCH.sh
# Opens web dashboard at http://127.0.0.1:8000
```

### During Market Hours

1. **Monitor Dashboard**
   - Watch live prices
   - Review mentor signal updates
   - Check position delta/theta

2. **Execute Trades**
   - Select symbol
   - Review signals confidence
   - Send order (will ask for confirmation)
   - Monitor fill

3. **Manage Positions**
   - Adjust stop-loss if needed
   - Move take-profit levels
   - Close when signal reverses

### Evening Shutdown

```bash
# Graceful shutdown
pkill -f "uvicorn backend.main"  # API
pkill -f "chrome.*remote-debugging"  # Chrome

# Or use restart script
source logs/restart_backend.sh   # Restart backend only
```

---

## 🐛 Troubleshooting

### Chrome Not Responding

**Problem**: "Just a moment..." page stays on screen

**Solutions**:
1. Click in Chrome window and press F5 (reload)
2. Complete Cloudflare challenge manually:
   - Click "Verify" button
   - Solve puzzle if asked
3. If stuck, kill Chrome and rerun:
   ```bash
   pkill -f "chrome.*remote-debugging"
   bash LIVE_LAUNCH.sh
   ```

### Order Entry Not Working

**Problem**: Order panel not detected, click fails

**Solutions**:
1. Verify browser is logged into broker:
   ```bash
   curl http://127.0.0.1:8000/status/execution | jq '.order_panel'
   ```
   Should show `"ready": true`

2. If `"ready": false`, browser likely on challenge page
3. Click in Chrome, verify you're on trading dashboard
4. Re-run selector calibration:
   ```bash
   bash LIVE_LAUNCH.sh
   ```
   It will recalibrate selectors

### API Slow or Unresponsive

**Problem**: Requests taking >5 seconds

**Solutions**:
1. Check backend logs:
   ```bash
   tail -f logs/backend.log | grep ERROR
   ```

2. Restart backend:
   ```bash
   source logs/restart_backend.sh
   ```

3. Kill and relaunch with fresh environment:
   ```bash
   bash LIVE_LAUNCH.sh
   ```

### Position Reconciliation Error

**Problem**: System position != Broker position

**Solutions**:
1. Force reconciliation:
   ```bash
   curl http://127.0.0.1:8000/admin/control/reconcile_positions
   ```

2. Check broker account for missing trades:
   - Log into MatchTrader directly
   - Verify positions match dashboard
   - If different, manually close trades in broker

3. Review journal logs:
   ```bash
   tail -f logs/execution_journal.log
   ```

---

## 📊 Performance Benchmarks

### Expected Performance (After Optimization)

| Operation | Time | Notes |
|-----------|------|-------|
| API `/status` | 10ms | Local, caching |
| `/mentor/context` | 100-500ms | Market data + AI |
| `/chart/data` | 50-200ms | Depends on candle count |
| Order execution | 200-400ms | Network + CDP |
| Live price update | 1000ms | Databento polling |

### Optimization Tips

1. **Reduce mentor polling**: Increase `MENTOR_POLLING_INTERVAL_SEC`
2. **Cache chart data**: Reduce `CHART_CANDLE_LIMIT`
3. **Batch selectors**: Load all symbols on startup
4. **Monitor CPU**: `top | grep python`

---

## 📞 Support & Debugging

### Debug Mode

Enable verbose logging:

```bash
# In .env
FASTAPI_LOG_LEVEL=debug
```

Restart backend:
```bash
source logs/restart_backend.sh
```

### File Locations

```
/workspaces/newcpu/
├── astroquant/                    # Main codebase
│   ├── backend/                   # FastAPI app
│   │   ├── main.py               # API routes
│   │   └── config.py             # Environment vars
│   ├── execution/                # Playwright + CDP
│   │   ├── playwright_engine.py  # CDP connector
│   │   └── matchtrader_executor.py
│   ├── engine/                   # Mentor AI
│   │   ├── mentor_engine_v3.py
│   │   └── multi_symbol_runner.py
│   ├── frontend/                 # Web dashboard
│   │   ├── index.html
│   │   └── api.js
│   └── data/                     # Configuration
│       └── matchtrader_selectors.json
├── logs/                          # Runtime logs
│   ├── backend.log
│   ├── chrome.log
│   └── live_launch.log
├── .env                           # Environment config
├── LIVE_LAUNCH.sh                 # Main launch script
└── STABILITY_CHECK.sh             # Verification script
```

---

## ✅ Final Checklist

- [x] Backend running (`http://127.0.0.1:8000`)
- [x] Chrome debugging enabled (CDP port 9222)
- [x] Databento market data live
- [x] Mentor engine responding
- [x] Chart system operational
- [x] Selector profile calibrated
- [x] Dashboard accessible
- [x] Order entry tested
- [x] Position reconciliation working
- [ ] **First live micro-lot trade confirmed**
- [ ] Daily loss limits verified
- [ ] Risk controls tested

---

## 🎯 Success Metrics

### System is Ready When:

✅ **Backend**: Responds in <50ms  
✅ **Chrome**: Connected via CDP, logged into broker  
✅ **Market Data**: Live prices updating every 1-2 seconds  
✅ **Mentor**: Confidence scores >0.6 on major signals  
✅ **Orders**: Execute within 200-400ms, no slippage >2 pips  
✅ **Risk**: All limit checks passing  

### System is NOT Ready If:

❌ Chrome shows "Just a moment..." (Cloudflare challenge)  
❌ Order panel detection failing  
❌ API requests timing out (>5 seconds)  
❌ Market data stale (>30 seconds old)  
❌ Positions don't reconcile with broker  

---

## 🚀 Go Live!

When ready:

```bash
# 1. Verify system is ready
bash STABILITY_CHECK.sh

# 2. Open dashboard
open http://127.0.0.1:8000
# (or use your browser: http://127.0.0.1:8000)

# 3. Execute first order
# - Select symbol (XAUUSD)
# - Review mentor signals
# - Send small order (0.01 lot)
# - Confirm execution
# - Monitor position

# 4. When confident, enable auto execution
# - Edit .env: ORDER_EXECUTION_MODE=auto
# - Restart backend: source logs/restart_backend.sh
# - Trades now execute automatically

# 🎉 Live trading active!
```

---

**AstroQuant System**: Built for production trading on CPU with real market data, AI signals, and automated risk management.

**Questions?** Check logs, read error messages, and validate against checklist above.

**Ready?** Run `bash LIVE_LAUNCH.sh` now!
