# AstroQuant / newcpu

Current readiness:
- Supervised live testing: ready
- Unattended production launch: blocked until the broker bridge is challenge-free and `preflight_unattended.sh` passes

Primary verification commands:

```bash
curl http://127.0.0.1:8000/status/broker_bridge | jq .
/workspaces/newcpu/.venv/bin/python -m pytest -q test_market_causality_router.py test_market_causality_fallback.py
bash preflight_strict.sh http://127.0.0.1:8000
bash preflight_unattended.sh http://127.0.0.1:8000
```

Interpretation:
- `preflight_strict.sh` green means the system is suitable for supervised live testing.
- `preflight_unattended.sh` green is required before unattended or automated launch.
- If `/status/broker_bridge` shows `broker_tab_title: Just a moment...` or `challenge_detected: true`, the broker session is still blocked by a challenge page.

Market causality contract verification:

```bash
bash run_market_causality_contracts.sh
```

This focused suite currently covers:
- Router contracts (normalization, cache TTL/recompute, reasoning delta progression)
- API contracts (`/market_causality/summary` and `/market_causality/status`)
- Frontend panel contract bindings
- End-to-end smoke path for summary payload and UI-critical fields

CI workflow:
- `.github/workflows/market-causality-contracts.yml`
- Runs on market-causality code or test changes and uploads JUnit + pytest text artifacts.