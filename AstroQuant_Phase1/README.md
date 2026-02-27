# AstroQuant Phase 1

Institutional core foundation backend for AstroQuant. Contains multi-symbol data ingestion, orderflow analysis, iceberg detection, fusion scoring, risk guard, and basic AI mentor narrative. REST API built with FastAPI.

## Setup

1. Create virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Add Databento API key to `.env`.
4. (Recommended for live/admin safety) add an admin key to `.env`:
   ```env
   ADMIN_API_KEY=your-strong-secret
   ```
   When set, control endpoints like auto-trading start/stop and emergency stop/start require `X-Admin-Key`.
   In browser console you can set it once with:
   ```js
   setAdminApiKey("your-strong-secret")
   ```
5. Configure execution symbol routing for Match-Trader symbols:
   ```env
   EXEC_SYMBOL_MAP=GC.FUT:XAUUSD,NQ.FUT:NAS100,YM.FUT:US30,6E.FUT:EURUSD,6B.FUT:GBPUSD,CL.FUT:USOIL
   EXEC_SPREAD_LIMITS=XAUUSD:30,NAS100:50,USOIL:80,US30:70,EURUSD:10,GBPUSD:12
   DATABENTO_RAW_SYMBOL_CANDIDATES=GC:GCZ6,GCG6,GCJ6;NQ:NQZ6,NQH7,NQM7;CL:CLZ6,CLF7,CLG7
   DATABENTO_END_LAG_MINUTES=10
   MARKET_FETCH_TIMEOUT_SECONDS=8
   MENTOR_FETCH_TIMEOUT_SECONDS=8
   ENGINES_ANALYZE_TIMEOUT_SECONDS=9
   ROLLOVER_CONTRACT_CHAINS=GC:GC.FUT,GCZ6,GCG6,GCJ6;NQ:NQ.FUT,NQZ6,NQH7,NQM7;CL:CL.FUT,CLZ6,CLF7,CLG7
   DATA_STALENESS_SECONDS=DEFAULT:300,GC:300,NQ:180,YM:180,ES:180,CL:360,6E:480,6B:480
   BROKER_FEED_POLL_MS=1000
   BACKEND_BASE_URL=http://127.0.0.1:8000
   ```
   You can change mapped targets to match your broker's exact symbols.
6. Run the server:
   ```bash
   uvicorn backend.main:app --reload
   ```

## Dev Restart Helper

- Restart backend (`:8000`) and frontend (`:5500`) cleanly with one command:
   ```bash
   ./restart_both.sh
   ```
- Stop both services cleanly with:
   ```bash
   ./stop_both.sh
   ```
- The script force-clears stale listeners on both ports, starts services, and validates health checks.
- Logs are written to:
   - `/tmp/aq_backend.log`
   - `/tmp/aq_frontend.log`

## Endpoints

- `GET /status` - returns service status
- `GET /analyze/{symbol}` - analyzes a symbol, returns fusion score, iceberg, and mentor narrative
- `GET /news/status?symbol=GCZ6` - normalized news guard output (`trade_halt`, `high_impact`, `reaction_bias`)
- `GET /prop/status` - prop phase/balance/progress status
- `GET /broker-feed/status` - broker sensor snapshot (admin key required)
- `GET /broker-feed/recent?limit=20` - recent broker feed snapshots with extraction diagnostics (admin key required)
- `GET /broker-brain/status` - execution adaptation layer status (admin key required)
- `POST /manual-trade` - trigger guarded manual trade execution (admin key required)
- `POST /alerts/broadcast` - broadcast operator alert via configured channel (admin key required)
- `POST /model-override` - switch governance mode (`SAFE`/`NORMAL`/`AGGRESSIVE`) (admin key required)
- `GET /model-override/status` - current model override mode and confidence threshold (admin key required)
- `WS /ws/broker-feed?interval=1.0` - local live stream of broker feed + broker brain state

## Operational Notes

- If `DATABENTO_API_KEY` is not configured, the service now stays up and uses fallback/generated bars for analysis views.
- For live trading quality, configure Databento and monitor `feed` health in the admin panel.
- Execution uses configurable mapping from analysis symbols to platform symbols (default includes `GC.FUT` -> `XAUUSD`, `NQ.FUT` -> `NAS100`, `YM.FUT` -> `US30`, `6E.FUT` -> `EURUSD`, `6B.FUT` -> `GBPUSD`, `CL.FUT` -> `USOIL`).

## Trade Universe (Default)

- `XAUUSD` <- `GC.FUT` (Priority: `PRIMARY`)
- `NAS100` <- `NQ.FUT` (Priority: `HIGH`)
- `US30` <- `YM.FUT` (Priority: `MEDIUM`)
- `EURUSD` <- `6E.FUT` (Priority: `STABLE`)
- `GBPUSD` <- `6B.FUT` (Priority: `VOLATILE`)
- `USOIL` <- `CL.FUT` (Priority: `NEWS-BASED`)

## 6-Model Auto Entry/Exit Logic

- Models used for consensus: `OrderFlow`, `Iceberg`, `ICT`, `Gann`, `Astro`, `Regime`.
- Entry requires priority-based minimum confidence and minimum agreeing model votes.
- `NEWS-BASED` symbols additionally require active news-impact context and are blocked on `trade_halt`.
- Exit signal is generated when active direction is reversed/neutralized by the 6-model consensus.

## Final Institutional Model Stack

- `ICT_LIQUIDITY`: liquidity sweep + BOS + FVG, RR `1:3`, risk `0.5%`, max `2` trades/session.
- `ICEBERG`: absorption continuation, RR `1:2.5`, risk `0.4%`, max `2` trades/session.
- `GANN`: cycle reversal, RR `1:2`, risk `0.5%`, max `1` trade/session.
- `NEWS_BREAKOUT`: high-impact breakout, RR `1:1.8`, risk `0.3%`, max `1` trade/session.
- `EXPANSION`: trend continuation, RR `1:2.5`, risk `0.4%`, max `2` trades/session.

Implementation mode is currently conservative: best valid model signal at a time (priority order in `engine/signal_manager.py`).

## Institutional AI Governance Mode (A + C)

- Multi-model concurrent scoring is active: all 5 models can emit signals per cycle.
- AI weighted selection is active through `engine/ai_decision_engine.py`.
- Score formula: `confidence × rr × model_weight × performance_boost`.
- Execution pipeline flow: `models -> scoring -> AI weighting -> risk filter -> execution` in `engine/execution_pipeline.py`.
- Global prop safety gates in pipeline: max `2` open trades and daily-loss hard filter.
- Adaptive model learning hook exists in `engine/model_performance.py` and is used by the AI decision engine.
- Concurrent execution rule: up to `2` trades can be opened in one cycle when top AI-ranked candidates are close-score and same-side aligned.
