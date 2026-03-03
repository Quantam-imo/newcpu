# AstroQuant v1 Architecture Freeze (Keep-All)

## Scope Locked
- Runtime target: Codespace/dev-container.
- Feature policy: keep all existing capabilities (Mentor, Learning, Clawbot, Telegram, Stress, Multi-symbol, Playwright, Admin).
- Refactor policy: no full rewrite; staged consolidation with backward compatibility.

## Source of Truth (v1)
- Core trading/domain orchestration: `engine/`
- API and transport boundary: `backend/`
- Broker/runtime execution boundary: `execution/`
- Frontend UI/runtime boundary: `frontend/`

## Canonical Runtime Flow
`market_data_service -> signal_manager -> ai_decision_engine -> ai_governance_engine -> risk_engine/risk_manager guardrails -> execution_manager -> trade_guardian -> journal/log -> mentor`

## Duplication Map (Current)
- Engine layer duplication perception:
  - `engine/*` is core strategy/governance/risk model layer.
  - `backend/engines/*` currently serves API overlay/support engines (news/cycle/liquidity + mentor-related adapters).
- AI layer fragmentation:
  - `ai/*`, `backend/ai/*`, `engine/learning_engine.py` coexist with partially overlapping concerns.
- Risk overlap:
  - `engine/risk_engine.py` (prop/rule lock runtime checks)
  - `engine/risk_manager.py` (account payload gate for pipeline selection)
- Execution overlap risk:
  - `engine/execution_pipeline.py` (selection and pre-trade gate)
  - `execution/execution_manager.py` (actual broker execution + final gate)

## Consolidation Decisions Applied
1. Governance hierarchy unified through singleton:
   - Added `engine/runtime_singletons.py`.
   - `ExecutionPipeline` and `ExecutionManager` now share one `AIGovernanceEngine` instance.
2. Pre-trade pipeline now checks governance before selecting candidates.

## Next Refactor Slices (Non-breaking)
1. Introduce one orchestrator module for analyze+execute path and reuse from:
   - `backend/routers/market.py`
   - `backend/multi_symbol_trader.py`
2. Split risk responsibilities clearly:
   - Keep `RiskEngine` as runtime authority.
   - Convert `RiskManager` into a thin adapter or deprecate it.
3. Normalize AI learning ownership:
   - Declare one canonical learning engine and route callers through it.
4. Mark `backend/engines/*` as API-overlay package explicitly and prevent strategy-logic drift from `engine/*`.

## Freeze Rules
- New strategy logic goes only to `engine/*`.
- New broker/execution logic goes only to `execution/*`.
- `backend/*` only composes, validates, and exposes APIs/ws.
- Keep compatibility shims until all callers migrate.
