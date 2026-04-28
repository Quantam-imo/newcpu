# MT5 Bridge Till-Date Update — Operational Summary
**Status: ✅ Ready for Regular Updates**  
**Generated: 2026-04-26**

## What Was Completed

### Infrastructure Hardening
1. **MT5 Bridge Daemon** (`tools/mt5_bridge_sync_daemon.py`)
   - Watches `market-causality-lab/data/live/mt5/incoming/` for MT5 CSV exports
   - Auto-detects newest file, waits for stability, processes 5m base feed
   - Auto-resamples to: 15m, 30m, 1h, 4h, 1d via pandas resample rules
   - Outputs:
     - **Live bridge files**: `XAUUSD_live_*_intraday.csv` (consumed by APIs)
     - **Canonical histories**: `XAU_*_data.csv` (persistent historical archive)
     - **Derived timeframes**: `XAU_1w_data.csv`, `XAU_1Month_data.csv` (auto-regenerated from daily)

2. **Startup Integration**
   - **tmux mode** (`start_24h.sh`): MT5 bridge runs in `aq-mt5-bridge` session
   - **Process mode** (`start_24h_fullstack.sh`): MT5 bridge launched via `start_mt5_bridge_sync.sh`
   - **Persistence guarantees**: `MT5_BRIDGE_PERSIST_HISTORY=1` hard-set in both paths
   - **Stop integration** (`stop_24h.sh`, `stop_24h_fullstack.sh`): Cleanly terminate bridge daemon

3. **Health Validation**
   - New `check_mt5_feed_health.sh` validates:
     - Incoming feed exists and is not too stale (24h tolerance)
     - Feed has minimum row count (50 rows = ~4 hours of 5m bars)
     - Warns if feed age > 1 hour (time to check MetaEditor exports)

### Data Status (as of 2026-04-26 11:33 UTC)

| Timeframe | Rows | Last Update | Lag | Status |
|-----------|------|-------------|-----|--------|
| 1m | 6,770,558 | 2025-12-31 23:59 | 2771h | ⚠️ Stale (no 1m source) |
| 5m | 1,907,477 | 2026-04-24 20:50 | 38.6h | ✅ Current |
| 15m | 531,753 | 2026-04-24 20:45 | 38.7h | ✅ Current |
| 30m | 326,231 | 2026-04-24 20:30 | 39.0h | ✅ Current |
| 1h | 164,358 | 2026-04-24 20:00 | 39.5h | ✅ Current |
| 4h | 42,863 | 2026-04-24 20:00 | 39.5h | ✅ Current |
| 1d | 6,980 | 2026-04-24 00:00 | 59.5h | ✅ Current |
| 1w | 1,368 | 2026-04-24 00:00 | 59.5h | ✅ Current |
| 1month | 316 | 2026-04-01 00:00 | 611.5h | ⏳ Monthly boundary OK |

**Bottom line**: 5m+ timeframes are till-date as of last market close (Friday). 1m is historical (no active 1m source).

## How to Use: Continuous Till-Date Updates

### Prerequisites: MetaEditor Export Flow
**You must set up regular MT5 exports to feed the system.**

1. **In MetaEditor Terminal**:
   - Select XAUUSD chart (any timeframe)
   - Right-click → **Export data** → Save CSV as:
     ```
     /workspaces/newcpu/market-causality-lab/data/live/mt5/incoming/XAUUSD_feed_latest.csv
     ```
   - Export **at least 300–500 bars** (4–7 hours of 5m data) for good overlap

2. **Automate Export** (Recommended):
   - Set a **cron job** or **MT5 script** to export every hour/4 hours:
     ```bash
     # Example cron: every 4 hours at :15 (e.g., 00:15, 04:15, 08:15, etc.)
     15 */4 * * * /path/to/export_script.sh
     ```
   - Or use MetaEditor automation to export on close of each 4h candle

### Start the System
```bash
cd /workspaces/newcpu

# Full 24/7 stack with MT5 bridge (tmux mode)
./start_24h.sh

# OR process-supervisor mode
./start_24h_fullstack.sh
```

Both paths:
1. Run health check (`check_mt5_feed_health.sh`)
2. Start MT5 bridge daemon with persistence enabled
3. Begin watching for new MT5 exports and updating canonical datasets

### Monitor Live Updates
```bash
# Check daemon status & feed age
./status_mt5_bridge_sync.sh

# View recent processing
tail -f /tmp/astroquant_mt5_bridge_sync.log

# Manual refresh (if you just exported new data from MetaEditor)
./tools/mt5_bridge_to_mcl.py \
  --input market-causality-lab/data/live/mt5/incoming/XAUUSD_feed_latest.csv \
  --persist-history \
  --data-dir market-causality-lab/data
```

### Stop the System
```bash
./stop_24h.sh          # tmux mode
# OR
./stop_24h_fullstack.sh  # process mode
```

## Technical Details

### Bridge Pipeline
```
MetaEditor Export (XAUUSD_feed_latest.csv)
    ↓
MT5 Bridge Daemon (watches incoming/)
    ↓
Parse & Validate (MT5 format → normalized OHLCV)
    ├─ Live Bridge Output (XAUUSD_live_5m_intraday.csv)
    └─ Canonical Persist (XAU_5m_data.csv) — kept up to 2.5M rows
    ↓
Auto-Resample to Higher TFs (15m → 30m → 1h → 4h → 1d)
    ├─ Live outputs (XAUUSD_live_*_intraday.csv)
    └─ Canonical persists (XAU_*_data.csv)
    ↓
Refresh Derived TFs (1w, 1month from 1d using pandas resample)
    └─ Canonical outputs (XAU_1w_data.csv, XAU_1Month_data.csv)
```

### Environment Variables (Customization)
Set in shell or in `start_mt5_bridge_sync.sh`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `MT5_BRIDGE_SOURCE_DIR` | `market-causality-lab/data/live/mt5/incoming` | Folder where MetaEditor exports go |
| `MT5_BRIDGE_OUT_DIR` | `market-causality-lab/data/live/mt5` | Output bridge files |
| `MT5_BRIDGE_DATA_DIR` | `market-causality-lab/data` | Canonical history archive |
| `MT5_BRIDGE_TIMEFRAME` | `5m` | Base timeframe (do not change) |
| `MT5_BRIDGE_PERSIST_HISTORY` | `1` | Enable canonical persistence (always 1) |
| `MT5_BRIDGE_POLL_SEC` | `1` | Check for new files every N seconds |
| `MT5_BRIDGE_STABLE_POLLS` | `1` | Wait this many polls before processing (prevents partial writes) |
| `MT5_BRIDGE_LAG_ALERT_SEC` | `15` | Warn if file is older than N seconds |
| `MT5_HEALTH_MAX_LAG_SEC` | `86400` | Fail startup if feed older than N seconds (24h) |
| `MT5_HEALTH_WARN_LAG_SEC` | `3600` | Warn if feed older than N seconds (1h) |

### What Happens with Incoming Data
When a new CSV is detected:
1. **Stability check**: Wait for file to stop changing (by default 1 poll = no-wait)
2. **Parse**: Load MT5 format (semicolon-delimited, DATE, Open, High, Low, Close, Volume)
3. **Normalize**: Convert to UTC, drop rows with missing close, sort by time
4. **Output bridge files**: Write live intraday + export copies
5. **Resample**: Generate 15m, 30m, 1h, 4h, 1d by resampling 5m
6. **Persist canonical**: Append normalized bars to `XAU_*_data.csv`, keep last 2.5M rows
7. **Refresh derived**: Regenerate 1w/1month from updated 1d
8. **Log**: Print summary including which files were persisted

## Known Limitations

1. **1-Minute Timeframe**: No active 1m MT5 source in current setup
   - To add: Set up separate MetaEditor export for 1m bars
   - Pipe to: `market-causality-lab/data/live/mt5/incoming/XAUUSD_1m_latest.csv`
   - Daemon will auto-detect and persist

2. **Historical Data Gaps**: Canonical CSVs started with 2000, but contain sparse/incomplete history before user supplied backfill
   - 5m/15m/30m/1h/4h/1d gap analysis: run `check_chart_data_flow.py`

3. **MetaEditor Export Responsibility**: User must configure automated exports or manually export at intervals
   - System watches passively; it does not pull from MetaEditor directly

4. **Multi-Symbol**: Currently hardcoded for XAUUSD
   - To add other symbols: Create `XAU_*_data.csv` → `EUR_*_data.csv`, etc.
   - Update bridge env: `MT5_BRIDGE_SYMBOL=EUR` (then mirror setup)

## Quick Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Bridge not running | `./status_mt5_bridge_sync.sh` | `./start_mt5_bridge_sync.sh` |
| Canonical files not updating | `stat market-causality-lab/data/XAU_5m_data.csv` | Ensure MetaEditor export fresh, check `MT5_BRIDGE_PERSIST_HISTORY=1` |
| Health check fails | `./check_mt5_feed_health.sh` | Export new data from MetaEditor to `incoming/XAUUSD_feed_latest.csv` |
| High lag in logs | `tail /tmp/astroquant_mt5_bridge_sync.log` | Feed file is stale; trigger new MetaEditor export |
| Rows not growing | Check `.../incoming/XAUUSD_feed_latest.csv` mtime | Export file hasn't been touched in 24h; resume MetaEditor exports |

## Next Steps

1. **Set up automated MetaEditor exports** (hourly or every 4h) to `incoming/XAUUSD_feed_latest.csv`
2. **Test with manual export**: 
   ```bash
   # After exporting from MetaEditor:
   ./check_mt5_feed_health.sh
   ./status_mt5_bridge_sync.sh
   ```
3. **Run full stack and monitor**:
   ```bash
   ./start_24h.sh
   # Watch logs in another terminal:
   tail -f logs/mt5_bridge_sync.log
   ```
4. **(Optional) Add 1m support** if needed for sub-5m strategies

---

**System is ready for continuous till-date operation.**  
**Just ensure MetaEditor exports happen regularly (hourly recommended).**
