from pathlib import Path

from fastapi.testclient import TestClient

from astroquant.backend.main import app
import astroquant.backend.router_market_causality as mcl_router


PANEL_PATH = Path("/workspaces/newcpu/astroquant/frontend/market_causality_panel.js")


def test_market_causality_end_to_end_smoke(monkeypatch):
    client = TestClient(app)
    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": "1h",
                "timeframe_fallback_applied": True,
                "timeframe_fallback_reason": "requested_timeframe_depth_below_target",
                "filtered_signal": "BUY",
                "confidence": 0.82,
                "quality": "high",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1500,
                "reasoning_display": {
                    "tone": "bullish",
                    "summary": "BUY bias with aligned trend and timing.",
                    "chain": ["phase and trend align", "risk gate is clear"],
                    "top_drivers": [{"label": "dominant_force", "score_pct": 65.0, "value": "BUY"}],
                },
                "process_timing": [{"name": "memory_probability_stack", "elapsed_ms": 12.5}],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    response = client.get(
        "/market_causality/summary",
        params={
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "lookback_years": 25,
            "source_mode": "historical_first",
            "refresh": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload.get("status") == "ok"
    assert payload.get("signal") == "BUY"
    assert payload.get("requested_timeframe") == "1m"
    assert payload.get("applied_timeframe") == "1h"
    assert payload.get("timeframe_fallback_applied") is True
    assert payload.get("reasoning_summary") == "BUY bias with aligned trend and timing."
    assert isinstance(payload.get("reasoning_delta"), dict)
    assert payload["reasoning_delta"].get("has_previous") is False

    panel_js = PANEL_PATH.read_text(encoding="utf-8")
    assert 'id="mclSignal"' in panel_js
    assert 'id="mclReasoningSummary"' in panel_js
    assert 'id="mclDeltaSignal"' in panel_js
    assert 'id="mclDeltaDrivers"' in panel_js
