# Release Notes - 2026-03-14

## Scope
Production lock pass for live execution reliability, manual testing safety, and launch gating.

## Commits
- `9e95980` Fix Playwright thread-affinity dispatch and enrich no-confirm diagnostics
- `81ec42c` Require symbol match for manual fill confirmation
- `7568376` Clamp manual test lots and bypass fixed-lot override
- `1ab37fe` Limit manual test lot range to 0.01-0.05
- `91d9118` Fix startup escape warning in symbol discovery script

## Key Outcomes
- Eliminated off-thread Playwright sync call paths responsible for greenlet thread-switch crashes.
- Added stronger diagnostics for submit/no-confirm behavior.
- Prevented false `EXECUTED` on manual probes caused by cross-symbol position row reads.
- Enforced manual test lot safety band to `0.01..0.05`.
- Added strict preflight gate script and integrated it into live launch flow.

## New Operational Gate
Run before live launch:

```bash
./preflight_strict.sh
```

The script fails fast if:
- Databento key is missing/placeholder.
- CDP endpoint is missing/unreachable.
- Execution status is not live/connected.

## Notes
- Runtime data churn file `astroquant/data/contract_resolver_cache.json` remains intentionally uncommitted in this release stream.
