from pathlib import Path

import astroquant.backend.router_market_causality as mcl_router
from astroquant.backend.router_market_causality import (
    _normalize_lookback_years,
    _normalize_source_mode,
    _normalize_symbol,
    _normalize_timeframe,
    _run_full_system,
)


def test_market_causality_normalization_defaults():
    assert _normalize_symbol("") == "XAUUSD"
    assert _normalize_timeframe("") == "1m"


def test_market_causality_normalization_transforms_values():
    assert _normalize_symbol(" gc.fut ") == "GC.FUT"
    assert _normalize_timeframe(" 15M ") == "15m"


def test_market_causality_normalization_source_mode_and_lookback():
    assert _normalize_source_mode("live_first") == "live_first"
    assert _normalize_source_mode("unsupported") == "historical_first"

    assert _normalize_lookback_years(25) == 25
    assert _normalize_lookback_years(0) == 1
    assert _normalize_lookback_years(999) == 100


def test_run_full_system_alignment_uses_payload_timeframes():
    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            return {
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": "1h",
                "timeframe_fallback_applied": True,
                "timeframe_fallback_reason": "requested_timeframe_depth_below_target",
            }

    payload, alignment = _run_full_system(
        _DummyModule(),
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )

    assert payload["applied_timeframe"] == "1h"
    assert alignment["requested_timeframe"] == "1m"
    assert alignment["applied_timeframe"] == "1h"
    assert alignment["timeframe_fallback_applied"] is True
    assert alignment["timeframe_fallback_reason"] == "requested_timeframe_depth_below_target"


def test_compute_summary_exposes_top_level_fallback_fields(monkeypatch):
    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            return {
                "data_source": "HISTORICAL CSV (XAU_1h_data.csv)",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": "1h",
                "timeframe_fallback_applied": True,
                "timeframe_fallback_reason": "requested_timeframe_depth_below_target",
                "applied_dataset_depth_years": 25.9,
                "filtered_signal": "BUY",
                "confidence": 0.8,
                "quality": "high",
                "final": {"phase": "expansion", "trend": "up"},
                "trap": {"trap": "none"},
                "decision_trace": {"reliability_score": 91},
                "simple": {"bias_score": 0.42, "bias_label": "bullish"},
                "news_guard_applied": False,
                "rejection_reason": None,
                "trade_levels": None,
                "institutional": {"institutional_decision": "BUY", "institutional_score": 0.7},
                "output_contracts": {"v": "test"},
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1234,
                "historical_depth_years": 25.9,
                "lookback_target_met": True,
                "lookback_depth_warning": None,
                "news_status": "missing_optional_file",
                "global_events_status": "missing_optional_file",
                "observation_id": "obs-123",
                "observation_log_path": "data/observation_logs/market_observations.csv",
                "observation": {
                    "trend_start_time": "2026-01-01T04:00:00",
                    "latest_time": "2026-01-01T05:00:00",
                    "news_previous_time": "2026-01-01T03:30:00",
                    "news_next_time": "2026-01-01T05:30:00",
                    "gann_degree": 182.0,
                    "geometry_angle_deg": 12.5,
                    "physics_velocity_price_per_hour": -2.1,
                    "price_time_ratio": 20.2,
                    "degree_time_ratio": 36.4,
                },
                "analysis_started_at_utc": "2026-01-01T05:00:00+00:00",
                "analysis_completed_at_utc": "2026-01-01T05:00:02+00:00",
                "analysis_elapsed_ms": 2000.0,
                "analysis_lifecycle": {
                    "started_at_utc": "2026-01-01T05:00:00+00:00",
                    "completed_at_utc": "2026-01-01T05:00:02+00:00",
                    "elapsed_ms": 2000.0,
                    "stages": [{"name": "data_loaded", "status": "completed", "detail": "ok"}],
                },
                "reasoning_display": {
                    "tone": "bullish",
                    "summary": "Signal BUY because phase expansion and trend up align with dominant force BUY.",
                    "chain": [
                        "Market structure reads as phase expansion with trend up.",
                        "Risk gate status: clear; rejection reason: none.",
                    ],
                    "evidence": {"dominant_force": "BUY"},
                    "top_drivers": [
                        {"label": "dominant_force", "value": "BUY", "score": 0.91},
                        {"label": "timing_window", "value": "POSSIBLE TURN", "score": 0.5},
                    ],
                },
                "process_timing": [
                    {"name": "memory_probability_stack", "elapsed_ms": 12.5},
                    {"name": "signal_synchronization", "elapsed_ms": 8.0},
                ],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())
    monkeypatch.setattr(
        mcl_router,
        "_module_path",
        lambda: Path("/workspaces/newcpu/market-causality-lab/main.py"),
    )

    payload = mcl_router._compute_summary(
        refresh=True,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )

    assert payload["status"] == "ok"
    assert payload["requested_timeframe"] == "1m"
    assert payload["applied_timeframe"] == "1h"
    assert payload["timeframe_fallback_applied"] is True
    assert payload["timeframe_fallback_reason"] == "requested_timeframe_depth_below_target"
    assert payload["applied_dataset_depth_years"] == 25.9
    assert payload["observation_id"] == "obs-123"
    assert payload["observation_trend_start_time"] == "2026-01-01T04:00:00"
    assert payload["observation_latest_time"] == "2026-01-01T05:00:00"
    assert payload["observation_gann_degree"] == 182.0
    assert payload["analysis_started_at_utc"] == "2026-01-01T05:00:00+00:00"
    assert payload["analysis_completed_at_utc"] == "2026-01-01T05:00:02+00:00"
    assert payload["reasoning_summary"].startswith("Signal BUY")
    assert payload["reasoning_chain"][0].startswith("Market structure")
    assert payload["reasoning_tone"] == "bullish"
    assert payload["reasoning_top_drivers"][0]["label"] == "dominant_force"
    assert payload["reasoning_delta"]["has_previous"] is False
    assert payload["reasoning_delta"]["previous_signal"] is None
    assert payload["reasoning_delta"]["signal_changed"] is False
    assert payload["reasoning_delta"]["top_driver_deltas"] == []
    assert payload["slowest_process_stage"]["name"] == "memory_probability_stack"
    assert payload["process_timing"][0]["elapsed_ms"] == 12.5


def test_compute_summary_reasoning_delta_consecutive_runs(monkeypatch):
    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()

    calls = {"n": 0}

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "data_source": "HISTORICAL CSV",
                    "symbol": symbol,
                    "requested_timeframe": timeframe,
                    "applied_timeframe": timeframe,
                    "filtered_signal": "BUY",
                    "reasoning_display": {
                        "tone": "bullish",
                        "summary": "Initial bullish read.",
                        "chain": ["Initial chain"],
                        "top_drivers": [
                            {"label": "dominant_force", "score_pct": 70.0},
                            {"label": "timing_window", "score_pct": 20.0},
                        ],
                    },
                    "process_timing": [],
                }

            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": "SELL",
                "reasoning_display": {
                    "tone": "bearish",
                    "summary": "Momentum faded.",
                    "chain": ["Updated chain"],
                    "top_drivers": [
                        {"label": "dominant_force", "score_pct": 40.0},
                        {"label": "timing_window", "score_pct": 45.0},
                        {"label": "risk_gate", "score_pct": 10.0},
                    ],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())
    monkeypatch.setattr(
        mcl_router,
        "_module_path",
        lambda: Path("/workspaces/newcpu/market-causality-lab/main.py"),
    )

    first = mcl_router._compute_summary(
        refresh=True,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )
    second = mcl_router._compute_summary(
        refresh=True,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )

    assert first["reasoning_delta"]["has_previous"] is False
    assert second["reasoning_delta"]["has_previous"] is True
    assert second["reasoning_delta"]["previous_signal"] == "BUY"
    assert second["reasoning_delta"]["signal_changed"] is True

    deltas = second["reasoning_delta"]["top_driver_deltas"]
    assert deltas[0]["label"] == "dominant_force"
    assert deltas[0]["delta_pct"] == -30.0
    assert deltas[1]["label"] == "timing_window"
    assert deltas[1]["delta_pct"] == 25.0
    assert deltas[2]["label"] == "risk_gate"
    assert deltas[2]["delta_pct"] == 10.0


def test_compute_summary_reasoning_delta_unchanged_signal(monkeypatch):
    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()

    calls = {"n": 0}

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            calls["n"] += 1
            if calls["n"] == 1:
                drivers = [
                    {"label": "dominant_force", "score_pct": 55.0},
                    {"label": "timing_window", "score_pct": 30.0},
                ]
            else:
                drivers = [
                    {"label": "dominant_force", "score_pct": 65.0},
                    {"label": "timing_window", "score_pct": 20.0},
                ]

            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": "BUY",
                "reasoning_display": {
                    "tone": "bullish",
                    "summary": "Signal remains BUY while weights rebalance.",
                    "chain": ["Chain"],
                    "top_drivers": drivers,
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())
    monkeypatch.setattr(
        mcl_router,
        "_module_path",
        lambda: Path("/workspaces/newcpu/market-causality-lab/main.py"),
    )

    _ = mcl_router._compute_summary(
        refresh=True,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )
    second = mcl_router._compute_summary(
        refresh=True,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )

    delta = second["reasoning_delta"]
    assert delta["has_previous"] is True
    assert delta["previous_signal"] == "BUY"
    assert delta["signal_changed"] is False

    top = delta["top_driver_deltas"]
    assert len(top) == 2
    assert top[0]["label"] == "dominant_force"
    assert top[0]["delta_pct"] == 10.0
    assert top[1]["label"] == "timing_window"
    assert top[1]["delta_pct"] == -10.0


def test_compute_summary_cache_reuse_and_refresh_forces_recompute(monkeypatch):
    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()

    calls = {"n": 0}

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            calls["n"] += 1
            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": f"SIGNAL_{calls['n']}",
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": f"run_{calls['n']}",
                    "chain": ["cache-check"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())
    monkeypatch.setattr(
        mcl_router,
        "_module_path",
        lambda: Path("/workspaces/newcpu/market-causality-lab/main.py"),
    )

    first = mcl_router._compute_summary(
        refresh=True,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )
    cached = mcl_router._compute_summary(
        refresh=False,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )
    refreshed = mcl_router._compute_summary(
        refresh=True,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )

    assert calls["n"] == 2
    assert first["signal"] == "SIGNAL_1"
    assert cached["signal"] == "SIGNAL_1"
    assert refreshed["signal"] == "SIGNAL_2"


def test_compute_summary_cache_expires_after_ttl(monkeypatch):
    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()

    calls = {"n": 0}

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            calls["n"] += 1
            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": f"TTL_{calls['n']}",
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "ttl-check",
                    "chain": ["ttl-check"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    fake_now = {"t": 1_000.0}

    def _fake_time() -> float:
        return fake_now["t"]

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())
    monkeypatch.setattr(
        mcl_router,
        "_module_path",
        lambda: Path("/workspaces/newcpu/market-causality-lab/main.py"),
    )
    monkeypatch.setattr(mcl_router.time, "time", _fake_time)

    first = mcl_router._compute_summary(
        refresh=True,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )

    fake_now["t"] += mcl_router._CACHE_TTL_SECONDS - 1
    within_ttl = mcl_router._compute_summary(
        refresh=False,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )

    fake_now["t"] += 2
    expired = mcl_router._compute_summary(
        refresh=False,
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        source_mode="historical_only",
    )

    assert calls["n"] == 2
    assert first["signal"] == "TTL_1"
    assert within_ttl["signal"] == "TTL_1"
    assert expired["signal"] == "TTL_2"
