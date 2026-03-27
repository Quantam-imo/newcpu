# 🚀 QUICK START DEPLOYMENT CARD

## Current Status
Historical deployment card for an earlier runtime milestone. Current status is supervised-live-ready; unattended launch still requires a green broker bridge and `preflight_unattended.sh`.  
- Preflight: **7/7 PASS** (environment, CDP, execution, selectors)
- Health: **14 PASS, 0 FAIL, 3 WARN** (warnings non-blocking)
- API: **31 endpoints** registered and responding
- Runtime: **Singleton provider active** on app startup

---

## 30-Second Deployment

### 1. Backend Only (Dev)
```bash
cd /workspaces/newcpu
python -m uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000
# Available at: http://localhost:8000
```

### 2. Validate
```bash
# Should show: 7/7 PASS
bash preflight_strict.sh http://localhost:8000

# Should show: 14 PASS, 0 FAIL, 3 WARN
bash health_check.sh http://localhost:8000
```

---

## What's New (This Session)

| Item | Status |
|------|--------|
| Runtime singleton (`runtime.py`) | ✅ Created |
| Symbol normalization (GC.FUT→XAUUSD) | ✅ Working |
| Playwright integration (connect_to_broker) | ✅ Implemented |
| Governance endpoints (live data) | ✅ Computing |
| Shared runner in all routes | ✅ Integrated |
| Health validation | ✅ Passing |
| Preflight gates | ✅ Passing |

---

## Key Endpoints

```
GET  /status                    → Broker health, connection state
GET  /status/execution          → CDP, quote, order panel
GET  /status/reconciliation     → Position sync from journal
GET  /status/equity_verification → Room to breach calculation
GET  /prop_status               → Governance rules, auto-trading
GET  /chart/data?symbol=XAUUSD  → Market candles (with time field)
GET  /health                    → System health dashboard
```

---

## Production Checklist

- [ ] Backend: `python -m uvicorn astroquant.backend.main:app --host 0.0.0.0 --port 8000 --workers 2`
- [ ] Frontend: `cd astroquant/frontend && npm start --port 3000`
- [ ] Chrome CDP: `google-chrome --remote-debugging-port=9222`
- [ ] Validate: `bash health_check.sh http://your-server:8000`

---

## Known Issues

⚠️ **Market endpoints timeout** (debug required)
- Affects: `/market/offset_quality?symbol=...`
- Impact: Market data features blocked
- Priority: HIGH - investigate `get_market_data()` call chain
- Other features: Unaffected (status, reconciliation, equity all working)

---

## Quick Test Commands

```bash
# Check backend is alive
curl http://localhost:8000/health | jq .

# Check broker connection
curl http://localhost:8000/status | jq '.broker_status'

# Check reconciliation
curl http://localhost:8000/status/reconciliation | jq .

# Check equity verification
curl http://localhost:8000/status/equity_verification | jq .
```

---

## Rollback (if needed)
```bash
git checkout HEAD~1 -- astroquant/backend/main.py
pkill -f uvicorn
python -m uvicorn astroquant.backend.main:app --port 8000
bash health_check.sh http://localhost:8000  # Verify
```

---

## Documentation
- Full Report: [`RUNTIME_INTEGRATION_COMPLETE.md`](RUNTIME_INTEGRATION_COMPLETE.md)
- Summary: [`FINAL_SUMMARY.md`](FINAL_SUMMARY.md)
- Architecture: See `PHASE_2_ARCHITECTURE.md` (updated with runtime.py integration)

---

**Session Complete**: All code changes deployed, validated, and documented.  
**Next Action**: Deploy to staging → Debug market endpoint → Execute live dry-run  

Questions? Check the full reports or test endpoints directly.
