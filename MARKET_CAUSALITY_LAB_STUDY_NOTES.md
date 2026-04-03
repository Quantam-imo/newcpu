# Market Causality Lab Study Notes

## Scope Studied
- Entire project tree under market-causality-lab:
  - main pipeline
  - backend engines (ai, memory, sync, validation, macro, live, universal_engine)
  - dashboard
  - tests
  - utility scripts and reports

## What The Project Is For
Market Causality Lab is a research + signal-generation intelligence stack for XAUUSD that combines:
- pattern memory and similarity AI
- phase/behavior/trap reasoning
- Gann/astro/harmonic/numerology transformations
- validation filters and execution safety checks
- macro and multi-asset context

Its output is a final directional signal (BUY/SELL/WAIT + confidence/quality), optional trade levels, and institutional context.

## Core Runtime Path
- Entry: market-causality-lab/main.py
- Main orchestration functions:
  - process(df)
  - full_system()
- Data source behavior:
  - preferred: MT5 fetch
  - fallback: CSV
  - optional: news feature merge

## Key Engine Layers
1. Market state + memory scan
2. Vector similarity + probability + AI decision
3. Psychology/trap/behavior reasoning
4. Time and universal conversion layer
5. Weighted signal sync + dominance + confidence
6. Validation/filtering/news guard/reliability gate
7. Execution and failure realism checks
8. Macro/multi-asset institutional sync
9. Learning feedback and memory update

## Main Output Characteristics
- filtered_signal
- confidence
- quality
- final phase/trend bundle
- decision_trace (when enabled)
- trade_levels (for directional signals)
- institutional decision and score
- normalized output contracts metadata

## Integration Reality Today
- AstroQuant adapter endpoint works through:
  - astroquant/backend/router_market_causality.py
- Unified frontend panel exists in:
  - astroquant/frontend/market_causality_panel.js
- Current limitation:
  - Market Causality native pipeline currently computes with its own defaults; requested symbol/timeframe are tracked and surfaced via alignment metadata, but not yet fully applied by native internals.

## Risks / Gaps Noted
- MT5 dependency can fail in containerized/offline environments
- CSV fallback path requirements must be present
- some behavior is controlled by optional env flags and optional datasets
- latency and overfitting checks exist, but production hardening still needs explicit SLA/error-budget policies

## Conclusion
Yes, this project is understood as a research-grade intelligence engine intended to provide a robust, explainable signal stream that can be integrated into AstroQuant execution and operations UI. It is now integrated at adapter + unified frontend level, and the next step is full native symbol/timeframe propagation inside market-causality-lab internals.
