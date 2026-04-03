# AstroQuant + Market Causality Lab Integration

## Objective
Run both systems behind one backend and one frontend so future features can be added without managing separate UIs.

## What is integrated now

### Backend bridge
- Added `astroquant/backend/router_market_causality.py`.
- Exposes:
  - `GET /market_causality/summary`
  - `GET /market_causality/status`
- Loads `market-causality-lab/main.py` dynamically via importlib.
- Adds market-causality-lab root to `sys.path` so `from backend...` imports resolve.
- Executes `full_system()` from the market-causality-lab working directory so relative data paths work.
- Uses a 30-second in-memory cache to avoid running the full intelligence pipeline on every request.

### AstroQuant app wiring
- `astroquant/backend/main.py` now includes the new market causality router.

### Single frontend integration
- Added `astroquant/frontend/market_causality_panel.js`.
- Added the script to `astroquant/frontend/index.html` canonical loader.
- The panel is toggled with the new `MCL Insight` button and shows:
  - signal
  - confidence
  - quality
  - phase / trend
  - trap / reliability / bias
  - news guard and rejection reason
  - institutional decision/score
  - trade levels
  - source and pipeline latency
- Refreshes every 15 seconds while panel is open.

## Integration flow
1. Frontend calls `/market_causality/summary`.
2. AstroQuant backend adapter executes Market Causality pipeline.
3. Adapter normalizes key fields to a compact summary contract.
4. Existing AstroQuant frontend renders the result in a dedicated panel.

## Contract (summary endpoint)
Current response fields include:
- `status`
- `signal`
- `confidence`
- `quality`
- `phase`
- `trend`
- `trap`
- `reliability_score`
- `bias_score`, `bias_label`
- `news_guard_applied`
- `rejection_reason`
- `trade_levels`
- `institutional_decision`, `institutional_score`
- `source`
- `elapsed_ms`
- `updated_at`

## Suggested next steps for further development
1. Move adapter cache from process memory to Redis so multiple workers share the same snapshot.
2. Add `POST /market_causality/recompute` with admin token guard to force recalculation.
3. Add symbol/timeframe parameters to summary endpoint and panel controls.
4. Convert market-causality-lab into an importable package to remove dynamic import complexity.
5. Add integration tests covering endpoint schema and panel rendering fallback states.
