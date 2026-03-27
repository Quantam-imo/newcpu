# Production Readiness Report

Date: 2026-03-07
Workspace: /workspaces/newcpu

Latest Verification Update: 2026-03-07 (crash/halt hardening validated under reconnect stress)

## 1) Project Inventory

### Active codebases
- `AstroQuant_Phase1/`
  - `backend/`: API, routers, service orchestration
  - `engine/`: strategy, risk, signal orchestration
  - `execution/`: Playwright execution layer and broker flow
  - `frontend/`: operations UI, mentor drawer, admin tooling
  - `ai/`: mentor/scoring helpers
  - `data/`: runtime state JSON
- `astroquant/`
  - `backend/`: main FastAPI backend + lifecycle
  - `engine/`: core engines + mentor v3 engines
  - `execution/`: MatchTrader executor + Playwright engine
  - `frontend/`: mirrored UI stack
  - `core/`, `telegram/`, `data/`, `logs/`

### Current approximate source footprint
- `AstroQuant_Phase1`: 65 Python files, 19 frontend files, 4 JSON files
- `astroquant`: 78 Python files, 18 frontend files, 5 JSON files

## 2) Live Readiness Snapshot (Current)

### Health
- Backend status endpoint: reachable
- Frontend status endpoint: reachable

### Execution readiness
- `preflight_strict.sh`: passing
- `/status/execution` is sufficient for supervised live testing when strict preflight is green
- Reconnect and recovery routes are restored in the active backend
- Playwright CDP attach now prefers the Maven trade tab instead of an arbitrary first page

### Broker bridge readiness
- `/status/broker_bridge` is the unattended production gate source of truth
- Current known blocking state:
  - `same_browser_mode: true`
  - `debugger_reachable: true`
  - `broker_tab_title: Just a moment...`
  - `challenge_detected: true`
  - `challenge_reason: cloudflare_challenge`
  - `order_panel.ready: false`
  - `quote: null`
- Result: supervised live testing is viable, unattended launch is not yet viable

### Reconnect/recovery path
- Reconnect endpoint is now blocking by default (safer than async mode for Playwright Sync API)
- Recovery endpoint actively attempts reconnect and selector recovery
- Repeated reconnect failures no longer self-halt execution via quote polling
- Recovery path remains available and clears historical halt state

### Mentor readiness
- `/mentor` endpoint responds and schema is present
- `/mentor/context` endpoint responds and schema is present
- Current market values are largely placeholders/empty (`price: 0.0` or `null`), requiring live feed validation

## 3) Pending Items Before Production

1. Broker challenge clearance in the remote-debug Chrome session
  - The Maven tab must no longer show `Just a moment...`
  - `/status/broker_bridge` must report `challenge_detected: false`
  - `preflight_unattended.sh` must return `UNATTENDED PREFLIGHT: READY`

2. Controlled live micro-lot validation (optional but recommended)
  - Dry-run BUY/SELL checks pass with `execute=false`
  - Explicit confirm-token live submit reached `result.status=EXECUTED` in manual-relaxed mode when CDP was healthy, with:
    - `confirm_clicked: true` (confirm selector handled)
    - `volume_set: true`
    - position row detected from open positions widget
  - Symbol-lock enforcement is now implemented: mismatched symbols are rejected before submit

3. Mentor data realism validation
	- Verify non-placeholder market values in `/mentor` and UI
	- Confirm data source mapping is stable under live feed

4. Working tree hygiene and release packaging
	- Separate runtime artifacts from source changes
	- Exclude transient files (`browser_session`, `__pycache__`, runtime data) from release scope

5. Final regression sweep
	- Ops UI status fields
	- Mentor drawer render path (`/mentor/context` + `/mentor` fallback)
	- Reconnect button flow
	- Backend startup/health consistency

## 4) Estimated Time To Production

### Best case
- 6-8 hours (single focused day)
- Preconditions: order panel appears immediately and selectors calibrate without redesign

### Realistic case
- 2-3 working days
- Includes calibration, dry runs, feed validation, regression, and packaging cleanup

### Conservative case
- 4-5 working days
- If broker DOM/session behavior is unstable or requires multiple selector/profile iterations

## 5) Immediate Critical Blocker

- Immediate blocker: broker-side challenge page in the Maven tab prevents unattended execution readiness.
- Technical paths are now hardened enough to report and gate this condition correctly.
- Remaining production steps are: clear broker challenge, confirm unattended preflight, verify mentor data realism, and complete release hygiene.

