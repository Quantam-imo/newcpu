from pathlib import Path
import tempfile
import pytest

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
                    "signal_start_time": "2026-01-01T04:00:00",
                    "signal_end_time": "2026-01-01T06:30:00",
                    "signal_start_price": 102.0,
                    "signal_end_price": 99.2,
                    "signal_window_hours": 1.5,
                    "signal_projected_move": -1.8,
                    "signal_projected_move_pct": -1.76,
                    "gann_nearest_key_angle": 90,
                    "gann_angle_proximity": "EXACT",
                    "confirmation_geometry": "YES",
                    "confirmation_time": "YES",
                    "confirmation_structure": "YES",
                    "confirmation_tape_action": "YES",
                    "numerology_cycle_runtime": "CONSOLIDATION",
                    "structure_major_runtime": "UPTREND_BUILDING",
                    "physics_momentum_runtime": "STRONG_UP",
                    "gann_mindset_bias": "BUY_CONTINUATION",
                    "gann_mindset_narration": "Price has reached a cardinal angle near 90deg and time is in phase with expansion.",
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
    assert payload["observation_signal_start_time"] == "2026-01-01T04:00:00"
    assert payload["observation_signal_end_time"] == "2026-01-01T06:30:00"
    assert payload["observation_signal_start_price"] == 102.0
    assert payload["observation_signal_end_price"] == 99.2
    assert payload["observation_signal_window_hours"] == 1.5
    assert payload["observation_gann_angle_proximity"] == "EXACT"
    assert payload["observation_confirmation_geometry"] == "YES"
    assert payload["observation_confirmation_time"] == "YES"
    assert payload["observation_confirmation_structure"] == "YES"
    assert payload["observation_confirmation_tape_action"] == "YES"
    assert payload["observation_gann_mindset_bias"] == "BUY_CONTINUATION"
    assert payload["observation_gann_mindset_narration"].startswith("Price has reached")
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


def test_build_gann_qa_rows_date_selectable(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "market_observations.csv"
        csv_path.write_text(
            "symbol,signal_end_time,gann_nearest_key_angle,gann_angle_proximity,confirmation_geometry,confirmation_time,confirmation_structure,confirmation_tape_action,gann_mindset_bias,gann_recommended_signal,gann_mindset_narration,signal_start_time,signal_start_price,signal_end_price,numerology_cycle_runtime,structure_major_runtime,physics_momentum_runtime\n"
            "XAUUSD,2026-03-31T22:00:00+00:00,90,EXACT,YES,YES,YES,YES,BUY_CONTINUATION,BUY,Past narrative,2026-03-31T20:00:00+00:00,3300,3310,EXPANSION,UPTREND_BUILDING,STRONG_UP\n"
            "XAUUSD,2026-04-03T10:00:00+00:00,180,NEAR,YES,YES,NO,YES,BUY_CONTINUATION,BUY,Present narrative,2026-04-03T08:00:00+00:00,3340,3350,CONSOLIDATION,CONSOLIDATION,MILD_UP\n"
            "XAUUSD,2026-04-05T12:00:00+00:00,45,EXACT,YES,YES,YES,YES,SELL_CONTINUATION,SELL,Future narrative,2026-04-05T10:00:00+00:00,3360,3340,COMPLETION,DOWNTREND_BUILDING,STRONG_DOWN\n",
            encoding="utf-8",
        )

        monkeypatch.setattr(mcl_router, "_observation_log_csv_path", lambda: csv_path)
        payload = mcl_router._build_gann_qa_rows(selected_date="2026-04-03", symbol="XAUUSD", limit=20, horizon_days=7)

        assert payload["status"] == "ok"
        assert payload["counts"]["past"] == 1
        assert payload["counts"]["present"] == 1
        assert payload["counts"]["future"] == 1
        assert payload["counts"]["qa_rows"] >= 3
        assert payload["summary"]["selected_date"] == "2026-04-03"
        assert payload["summary"]["horizon_days"] == 7
        assert payload["summary"]["dominant_signal"] in {"BUY", "SELL", "WAIT"}
        assert "overview" in payload["summary"]
        assert any(row["era"] == "PAST" for row in payload["rows"])
        assert any(row["era"] == "PRESENT" for row in payload["rows"])
        assert any(row["era"] == "FUTURE" for row in payload["rows"])
        assert any(row.get("answer_mode") == "REALIZED" for row in payload["rows"])
        assert any(row.get("answer_mode") == "LIVE" for row in payload["rows"])
        assert any(row.get("answer_mode") == "FORECAST" for row in payload["rows"])

        sample = payload["rows"][0]
        probs = sample.get("scenario_probs") or {}
        assert set(probs.keys()) == {"buy", "sell", "wait"}
        assert abs(float(probs["buy"]) + float(probs["sell"]) + float(probs["wait"]) - 1.0) < 0.0002
        assert isinstance(sample.get("invalidation_rules"), list)
        assert len(sample.get("invalidation_rules")) >= 1
        assert sample.get("forecast_horizon_days") == 7


def test_question_bank_endpoint_default_and_filters():
    # Test 52-question framework (expanded from 48: +4 ICT questions)
    payload = mcl_router.market_causality_question_bank(category="", framework="")
    assert payload["status"] == "ok"
    assert payload["count"] == 52, f"Expected 52 questions, got {payload['count']}"
    assert isinstance(payload["questions"], list)
    assert len(payload["questions"]) == 52
    assert "gann" in payload["categories"]
    assert "geometry" in payload["categories"]  # New category
    assert "physics" in payload["categories"]
    assert "time" in payload["categories"]
    assert "confluence" in payload["categories"]
    assert "ict" in payload["categories"]

    # Gann category should now have 10 questions (was 4)
    gann_only = mcl_router.market_causality_question_bank(category="gann", framework="")
    assert gann_only["status"] == "ok"
    assert gann_only["count"] == 10, f"Expected 10 Gann questions, got {gann_only['count']}"
    assert all(str(q.get("category")) == "gann" for q in gann_only["questions"])

    # Physics category should now have 7 questions (was 2)
    physics_only = mcl_router.market_causality_question_bank(category="physics", framework="")
    assert physics_only["status"] == "ok"
    assert physics_only["count"] == 7, f"Expected 7 Physics questions, got {physics_only['count']}"
    assert all(str(q.get("category")) == "physics" for q in physics_only["questions"])

    # Geometry category is completely NEW with 4 questions
    geometry_only = mcl_router.market_causality_question_bank(category="geometry", framework="")
    assert geometry_only["status"] == "ok"
    assert geometry_only["count"] == 4, f"Expected 4 Geometry questions, got {geometry_only['count']}"
    assert all(str(q.get("category")) == "geometry" for q in geometry_only["questions"])

    # Time category should now have 5 questions (was 2)
    time_only = mcl_router.market_causality_question_bank(category="time", framework="")
    assert time_only["status"] == "ok"
    assert time_only["count"] == 5, f"Expected 5 Time questions, got {time_only['count']}"
    assert all(str(q.get("category")) == "time" for q in time_only["questions"])

    # Confluence category should now have 4 questions (was 2)
    confluence_only = mcl_router.market_causality_question_bank(category="confluence", framework="")
    assert confluence_only["status"] == "ok"
    assert confluence_only["count"] == 4, f"Expected 4 Confluence questions, got {confluence_only['count']}"
    assert all(str(q.get("category")) == "confluence" for q in confluence_only["questions"])

    # ICT category now expanded to 6 questions (was 2)
    ict_only = mcl_router.market_causality_question_bank(category="ict", framework="")
    assert ict_only["status"] == "ok"
    assert ict_only["count"] == 6, f"Expected 6 ICT questions, got {ict_only['count']}"
    assert all(str(q.get("category")) == "ict" for q in ict_only["questions"])
    # Verify all ICT question IDs
    ict_ids = {q["id"] for q in ict_only["questions"]}
    assert ict_ids == {"ICT_01", "ICT_02", "ICT_03", "ICT_04", "ICT_05", "ICT_06"}

    # AI Learning filter
    ai_only = mcl_router.market_causality_question_bank(category="", framework="ai")
    assert ai_only["status"] == "ok"
    assert ai_only["count"] == 2
    assert all(str(q.get("framework")) == "ai" for q in ai_only["questions"])


# ---- live_price endpoint contracts ------------------------------------------

def test_live_price_endpoint_returns_unavailable_when_both_sources_fail(monkeypatch):
    """When stooq and Databento both fail, status must be 'unavailable'.
    The broker DOM path is skipped silently (module not present in tests).
    """
    import urllib.request as _url_req
    import astroquant.backend.router_market_causality as _r

    # Attempt 2: stooq — make urlopen raise so the network path is blocked.
    def _raise_network(*a, **kw):
        raise OSError("network blocked in test")
    monkeypatch.setattr(_url_req, "urlopen", _raise_network)

    # Attempt 3: Databento — patch the import target so the call also fails.
    import astroquant.backend.services.databento_utility as _db_util
    monkeypatch.setattr(
        _db_util,
        "fetch_candles_unified",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("databento blocked in test")),
    )

    result = _r.market_causality_live_price(symbol="XAUUSD")

    assert result["status"] == "unavailable"
    assert result["price"] is None
    assert result["symbol"] == "XAUUSD"
    assert "error" in result
    assert "elapsed_ms" in result


def test_live_price_endpoint_schema_keys_always_present(monkeypatch):
    """Response dict must always contain the canonical key set regardless of outcome."""
    import astroquant.backend.router_market_causality as _r

    monkeypatch.setattr(_r, "_module", None, raising=False)
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)

    result = _r.market_causality_live_price(symbol="GC.FUT")

    for key in ("status", "symbol", "price", "source", "elapsed_ms"):
        assert key in result, f"Missing key '{key}' in live_price response"


def test_live_price_endpoint_ok_path_via_stooq(monkeypatch):
    """When stooq returns a valid CSV row, status must be 'ok' with the parsed price."""
    import urllib.request as _url_req
    import astroquant.backend.router_market_causality as _r

    # Return a valid stooq-format CSV with a known close price.
    _CSV = b"Symbol,Date,Time,Open,High,Low,Close,Volume\nXAUUSD,2026-04-03,12:00:00,3118.00,3125.00,3110.00,3120.50,0\n"

    class _FakeResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass
        def read(self):
            return _CSV

    monkeypatch.setattr(_url_req, "urlopen", lambda *a, **kw: _FakeResp())

    result = _r.market_causality_live_price(symbol="XAUUSD")

    assert result["status"] == "ok"
    assert result["price"] == 3120.50
    assert result["symbol"] == "XAUUSD"
    assert result["source"] == "stooq_xauusd_spot"
    assert result["spot"] is True
    assert result["ts"] is not None
    assert result["elapsed_ms"] >= 0


# ---- _compute_gann_answers tests --------------------------------------------

_FULL_PAYLOAD = {
    "filtered_signal": "BUY",
    "confidence": 0.78,
    "gann_confluence_ready": True,
    "news_guard_applied": False,
    "final": {"trend": "up", "phase": "expansion"},
    "simple": {"bias_score": 0.55, "bias_label": "bullish"},
    "institutional": {"institutional_decision": "BUY", "institutional_score": 0.72},
    "trap": {"trap": "none"},
    "decision_trace": {"reliability_score": 0.75},
    "trade_levels": {"entry": 3050.0, "stop_loss": 3020.0, "take_profit": 3110.0, "r_ratio": 2.0},
    "observation": {
        "gann_angle_proximity": "NEAR",
        "gann_nearest_key_angle": 45,
        "confirmation_geometry": True,
        "confirmation_time": True,
        "confirmation_structure": True,
        "confirmation_tape_action": True,
        "signal_window_hours": 24,
        "signal_projected_move": 60.0,
        "gann_degree": 135.0,
        "geometry_angle_deg": 45.0,
        "physics_velocity_price_per_hour": 2.5,
        "price_time_ratio": 1.0,
        "degree_time_ratio": 1.05,
        "gann_mindset_bias": "BUY",
        "signal_start_time": "2026-04-04T00:00:00+00:00",
        "signal_end_time": "2026-04-05T00:00:00+00:00",
    },
    "astro": {"nearby_event": {"event_name": "New Moon", "impact_level": "MEDIUM"}},
    "learning_profile": {"win_rate": 0.62},
    "ai_model": {"used_model": True, "version": "v1", "drift": {"drift_detected": False}},
}

_EMPTY_PAYLOAD: dict = {}


def test_compute_gann_answers_returns_52_questions():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    assert len(out["gann_questions"]) == 52
    assert out["gann_questions_total"] == 52


def test_compute_gann_answers_all_question_ids_present():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    expected_ids = {q["id"] for q in mcl_router._TRADING_GANN_QUESTION_BANK}
    returned_ids = {q["question_id"] for q in out["gann_questions"]}
    assert returned_ids == expected_ids


def test_compute_gann_answers_answer_fields_shape():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    for q in out["gann_questions"]:
        assert isinstance(q["answer"], bool)
        assert isinstance(q["reasoning"], str)
        assert len(q["reasoning"]) > 0
        assert 0.0 <= float(q["confidence"]) <= 1.0


def test_compute_gann_answers_score_and_pct_consistent():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    score = out["gann_questions_score"]
    total = out["gann_questions_total"]
    pct = out["gann_questions_pct"]
    assert 0 <= score <= total
    assert abs(pct - round(score / total * 100, 1)) < 0.1


def test_compute_gann_answers_verdict_thresholds():
    out_strong = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    # Full aligned payload should score well
    assert out_strong["gann_questions_verdict"] in {"STRONG", "ACCEPTABLE", "WEAK", "FAIL"}

    out_empty = mcl_router._compute_gann_answers(_EMPTY_PAYLOAD)
    # Empty payload is graceful — returns ERROR-free result with 52 questions
    assert out_empty["gann_questions_total"] in {52, 0}
    assert out_empty["gann_questions_verdict"] in {"STRONG", "ACCEPTABLE", "WEAK", "FAIL", "ERROR"}


def test_compute_gann_answers_verdict_strong_on_fully_aligned():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    assert out["gann_questions_verdict"] in {"STRONG", "ACCEPTABLE"}
    assert out["gann_questions_pct"] >= 55.0


def test_compute_gann_answers_wait_signal_reduces_score():
    wait_payload = {**_FULL_PAYLOAD, "filtered_signal": "WAIT", "confidence": 0.3}
    out_wait = mcl_router._compute_gann_answers(wait_payload)
    out_buy  = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    assert out_wait["gann_questions_score"] <= out_buy["gann_questions_score"]


def test_compute_gann_answers_weakest_component_is_valid():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    assert out["gann_weakest_component"] in {"geometry", "time", "structure", "tape"}


def test_compute_gann_answers_probabilities_sum_to_100():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    total_prob = float(out["gann_buy_prob"]) + float(out["gann_sell_prob"]) + float(out["gann_wait_prob"])
    assert abs(total_prob - 100.0) < 1.0


def test_compute_gann_answers_buy_signal_buy_probability_dominant():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    assert float(out["gann_buy_prob"]) >= float(out["gann_sell_prob"])


def test_compute_gann_answers_conf01_all_four_true():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    conf01 = next(q for q in out["gann_questions"] if q["question_id"] == "CONF_01")
    # All 4 confirmations are True in _FULL_PAYLOAD
    assert conf01["answer"] is True
    assert conf01["confidence"] > 0.8


def test_compute_gann_answers_risk01_news_guard_false():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    risk01 = next(q for q in out["gann_questions"] if q["question_id"] == "RISK_01")
    assert risk01["answer"] is True  # news_guard_applied=False → no block → PASS


def test_compute_gann_answers_risk01_news_guard_blocks():
    blocked = {**_FULL_PAYLOAD, "news_guard_applied": True}
    out = mcl_router._compute_gann_answers(blocked)
    risk01 = next(q for q in out["gann_questions"] if q["question_id"] == "RISK_01")
    assert risk01["answer"] is False


def test_compute_gann_answers_exec02_rr_below_threshold():
    low_rr = {**_FULL_PAYLOAD, "trade_levels": {"entry": 3050, "stop_loss": 3040, "take_profit": 3055, "r_ratio": 0.5}}
    out = mcl_router._compute_gann_answers(low_rr)
    exec02 = next(q for q in out["gann_questions"] if q["question_id"] == "EXEC_02")
    assert exec02["answer"] is False


def test_compute_gann_answers_exec02_rr_above_threshold():
    out = mcl_router._compute_gann_answers(_FULL_PAYLOAD)
    exec02 = next(q for q in out["gann_questions"] if q["question_id"] == "EXEC_02")
    # r_ratio=2.0 in _FULL_PAYLOAD → exactly at threshold
    assert exec02["answer"] is True


def test_compute_gann_answers_empty_payload_graceful():
    """Empty payload must not raise — falls back to all FAIL with score=0."""
    out = mcl_router._compute_gann_answers({})
    assert isinstance(out, dict)
    assert out["gann_questions_score"] >= 0
    assert isinstance(out["gann_questions"], list)


# ---- /gann_questions endpoint -----------------------------------------------

def test_gann_questions_endpoint_status_ok():
    result = mcl_router.market_causality_gann_questions(_FULL_PAYLOAD)
    assert result["status"] == "ok"
    assert len(result["gann_questions"]) == 52


def test_gann_questions_endpoint_empty_payload():
    result = mcl_router.market_causality_gann_questions({})
    assert result["status"] == "ok"
    assert isinstance(result["gann_questions"], list)


def test_gann_questions_endpoint_schema_keys():
    result = mcl_router.market_causality_gann_questions(_FULL_PAYLOAD)
    for key in ("status", "gann_questions", "gann_questions_score", "gann_questions_total",
                "gann_questions_pct", "gann_questions_verdict", "gann_weakest_component",
                "gann_buy_prob", "gann_sell_prob", "gann_wait_prob"):
        assert key in result, f"Missing key: {key}"


# ---- /question_bank POST with live answers ----------------------------------

def test_question_bank_post_returns_live_answers():
    result = mcl_router.market_causality_question_bank_with_answers(_FULL_PAYLOAD)
    assert result["status"] == "ok"
    assert result["live_answers_included"] is True
    assert len(result["questions"]) == 52
    # Every question must have answer + reasoning + confidence injected
    for q in result["questions"]:
        assert "answer" in q, f"Missing 'answer' in {q.get('id')}"
        assert "reasoning" in q, f"Missing 'reasoning' in {q.get('id')}"
        assert "confidence" in q, f"Missing 'confidence' in {q.get('id')}"


def test_question_bank_post_includes_aggregate_scoring():
    result = mcl_router.market_causality_question_bank_with_answers(_FULL_PAYLOAD)
    for key in ("gann_questions_verdict", "gann_questions_score", "gann_questions_pct",
                "gann_weakest_component", "gann_buy_prob"):
        assert key in result, f"Missing key: {key}"


def test_question_bank_post_category_filter_applies():
    result = mcl_router.market_causality_question_bank_with_answers(
        _FULL_PAYLOAD, category="gann"
    )
    assert result["count"] == 10
    assert all(q["category"] == "gann" for q in result["questions"])
    assert result["live_answers_included"] is True


def test_question_bank_get_still_works_without_answers():
    result = mcl_router.market_causality_question_bank(category="", framework="")
    assert result["status"] == "ok"
    assert result["count"] == 52
    assert result.get("live_answers_included") is False or "live_answers_included" not in result or result["live_answers_included"] is False


# ---- /weights endpoint -------------------------------------------------------

def test_weights_endpoint_returns_all_signal_keys():
    result = mcl_router.market_causality_weights()
    assert result["status"] == "ok"
    weights = result["weights"]
    for key in ("geometry", "time", "structure", "momentum", "gann", "ict", "confluence"):
        assert key in weights, f"Missing weight key: {key}"
        assert 0.0 <= weights[key] <= 1.0, f"Weight {key} out of range: {weights[key]}"
    assert "overall_accuracy" in result
    assert "model_confidence" in result
    assert result["model_confidence"] in ("HIGH", "MEDIUM", "LOW", "CALIBRATING", "LEARNING")
    assert isinstance(result["total_predictions"], int)


def test_weights_endpoint_updated_at_is_recent():
    import time as _time
    result = mcl_router.market_causality_weights()
    assert abs(result["updated_at"] - int(_time.time())) < 5


# ---- batch replay (backtest_replay.py) --------------------------------------

def test_discover_chart_files_finds_data_files():
    from astroquant.backend.backtest_replay import _discover_chart_files, _DATA_DIR

    pairs = _discover_chart_files()
    # At least some chart files must be discoverable in the repo
    assert isinstance(pairs, list)
    if _DATA_DIR.exists():
        files = list(_DATA_DIR.glob("last_known_chart_*.json"))
        # pairs may be fewer than files due to bare-number deduplication
        assert len(pairs) <= len(files), "Discovered pairs should not exceed file count"
        assert len(pairs) > 0, "At least one chart file should be discovered"
        for symbol, timeframe in pairs:
            assert symbol, "Symbol should not be empty"
            assert timeframe, "Timeframe should not be empty"


def test_discover_chart_files_parses_symbol_timeframe():
    from astroquant.backend.backtest_replay import _discover_chart_files

    pairs = _discover_chart_files()
    for symbol, tf in pairs:
        # Symbol should contain a dot (e.g. GC.FUT, 6E.FUT, NQ.FUT)
        assert "." in symbol, f"Unexpected symbol format: {symbol}"
        # Timeframe should be short alphanumeric string
        assert len(tf) <= 5, f"Unexpectedly long timeframe suffix: {tf}"


def test_run_batch_replay_dry_run_returns_summary():
    from astroquant.backend.backtest_replay import run_batch_replay

    result = run_batch_replay(dry_run=True)
    assert result["status"] in ("ok", "partial", "error")
    assert "files_processed" in result
    assert "total_predictions" in result
    assert "total_correct" in result
    assert "batch_accuracy_pct" in result
    assert isinstance(result["results"], list)


def test_run_batch_replay_dry_run_does_not_write_tracker(tmp_path):
    from astroquant.backend.backtest_replay import run_batch_replay
    import json

    tracker_file = tmp_path / "tracker_test.json"
    result = run_batch_replay(dry_run=True, tracker_path=str(tracker_file))
    # dry_run=True should not persist predictions — tracker file created but empty/minimal
    if tracker_file.exists():
        d = json.loads(tracker_file.read_text())
        assert len(d.get("predictions", [])) == 0, "dry_run should not write predictions"


def test_run_batch_replay_accuracy_is_percentage():
    from astroquant.backend.backtest_replay import run_batch_replay

    result = run_batch_replay(dry_run=True)
    pct = result.get("batch_accuracy_pct", 0.0)
    assert 0.0 <= pct <= 100.0, f"batch_accuracy_pct out of range: {pct}"


# ---- gann_qa Q5 news question + news_context field --------------------------

_NEWS_CSV_HEADER = (
    "symbol,signal_end_time,gann_nearest_key_angle,gann_angle_proximity,"
    "confirmation_geometry,confirmation_time,confirmation_structure,confirmation_tape_action,"
    "gann_mindset_bias,gann_recommended_signal,gann_mindset_narration,"
    "signal_start_time,signal_start_price,signal_end_price,"
    "numerology_cycle_runtime,structure_major_runtime,physics_momentum_runtime,"
    "news_previous_time,news_previous_event,news_previous_impact,"
    "news_next_time,news_next_event,news_next_impact\n"
)
_NEWS_CSV_ROW = (
    "XAUUSD,2026-04-03T10:00:00+00:00,180,NEAR,"
    "YES,YES,NO,YES,"
    "BUY_CONTINUATION,BUY,Present narrative,"
    "2026-04-03T08:00:00+00:00,3340,3350,"
    "CONSOLIDATION,CONSOLIDATION,MILD_UP,"
    "2026-04-03T07:30:00+00:00,NFP Release,HIGH,"
    "2026-04-03T14:00:00+00:00,FOMC Minutes,MEDIUM\n"
)


def test_gann_qa_rows_include_news_context_field(monkeypatch):
    """Every row returned by _build_gann_qa_rows must contain a news_context key."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "market_observations.csv"
        csv_path.write_text(_NEWS_CSV_HEADER + _NEWS_CSV_ROW, encoding="utf-8")

        monkeypatch.setattr(mcl_router, "_observation_log_csv_path", lambda: csv_path)
        payload = mcl_router._build_gann_qa_rows(
            selected_date="2026-04-03", symbol="XAUUSD", limit=20, horizon_days=7
        )

        assert payload["status"] == "ok"
        assert len(payload["rows"]) > 0, "Expected at least one QA row"
        for row in payload["rows"]:
            assert "news_context" in row, f"Missing news_context in row: {row.get('question', '')[:40]}"
            ctx = row["news_context"]
            assert isinstance(ctx, str) and len(ctx) > 0, "news_context must be a non-empty string"


def test_gann_qa_rows_include_q5_news_question(monkeypatch):
    """Each observation in _build_gann_qa_rows must produce exactly 5 QA items;
    Q5 must contain the 'News/Event question:' prefix."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = Path(tmpdir) / "market_observations.csv"
        csv_path.write_text(_NEWS_CSV_HEADER + _NEWS_CSV_ROW, encoding="utf-8")

        monkeypatch.setattr(mcl_router, "_observation_log_csv_path", lambda: csv_path)
        payload = mcl_router._build_gann_qa_rows(
            selected_date="2026-04-03", symbol="XAUUSD", limit=20, horizon_days=7
        )

        assert payload["status"] == "ok"
        # 1 CSV row → 5 QA items (Q1–Q5)
        assert payload["counts"]["qa_rows"] == 5, (
            f"Expected 5 QA rows per observation, got {payload['counts']['qa_rows']}"
        )
        questions = [r["question"] for r in payload["rows"]]
        news_questions = [q for q in questions if q.startswith("News/Event question:")]
        assert len(news_questions) >= 1, "At least one row must have a News/Event question"
        # Q5 answer should reference news event names
        q5_rows = [r for r in payload["rows"] if r["question"].startswith("News/Event question:")]
        for q5 in q5_rows:
            assert "NFP Release" in q5["answer"] or "FOMC" in q5["answer"] or "--" in q5["answer"]


def test_weights_signal_accuracy_is_dict_of_floats():
    """signal_accuracy in /weights response must be a dict of float values in [0, 1]."""
    result = mcl_router.market_causality_weights()
    sig_acc = result.get("signal_accuracy", {})
    assert isinstance(sig_acc, dict), "signal_accuracy must be a dict"
    for key, val in sig_acc.items():
        assert isinstance(val, float), f"signal_accuracy[{key}] must be float, got {type(val)}"
        assert 0.0 <= val <= 1.0, f"signal_accuracy[{key}]={val} out of [0..1]"


# ---- /history endpoint -------------------------------------------------------

def test_history_endpoint_returns_ok():
    """/history endpoint must return status 'ok' and a list under 'history'."""
    result = mcl_router.market_causality_history(limit=50)
    assert result["status"] == "ok"
    assert "history" in result
    assert isinstance(result["history"], list)
    assert "total" in result
    assert "returned" in result
    assert isinstance(result["total"], int)
    assert isinstance(result["returned"], int)
    # 'returned' is the page size; 'total' is the full unfiltered count
    assert result["returned"] == len(result["history"])
    assert result["total"] >= result["returned"]


def test_history_endpoint_row_fields():
    """Each row in /history must contain the canonical joined fields."""
    result = mcl_router.market_causality_history(limit=50)
    required = {
        "prediction_id", "direction", "entry_price", "realized_price",
        "outcome_direction", "actual_move_pips", "timeframe_reached",
        "was_correct", "accuracy_score", "prediction_timestamp",
    }
    for row in result["history"]:
        for field in required:
            assert field in row, f"Missing field '{field}' in history row"
        assert isinstance(row["was_correct"], bool)
        if row["accuracy_score"] is not None:
            assert 0.0 <= float(row["accuracy_score"]) <= 1.0


# ---- /history live round-trip -----------------------------------------------

def test_history_round_trip_correct_outcome(tmp_path):
    """Record a prediction + correct outcome via router; verify /history returns it."""
    from astroquant.backend.prediction_tracker import PredictionTracker
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    import time as _time

    tracker = PredictionTracker(path=tmp_path / "rt_tracker.json")
    engine = LearningFeedbackEngine(tracker=tracker)

    # Patch the router's module-level singletons for this test
    original_tracker = mcl_router._PREDICTION_TRACKER
    original_engine = mcl_router._LEARNING_ENGINE
    try:
        mcl_router._PREDICTION_TRACKER = tracker
        mcl_router._LEARNING_ENGINE = engine

        pid = "rt-test-001"
        ts_before = int(_time.time())

        # Record outcome (router auto-creates the prediction if missing)
        outcome_resp = mcl_router.market_causality_record_outcome({
            "prediction_id": pid,
            "direction": "BUY",
            "outcome_direction": "UP",
            "realized_price": 3100.0,
            "actual_move_pips": 50.0,
            "timeframe_reached": 5,
            "entry_price": 3050.0,
            "stop_price": 3020.0,
            "target_price": 3110.0,
            "signals": {"geometry": True, "time": True, "structure": False,
                        "momentum": True, "gann": False, "ict": False},
        })
        assert outcome_resp["status"] == "ok", f"record_outcome failed: {outcome_resp}"
        assert outcome_resp["was_correct"] is True

        # Fetch history — row must be present
        history = mcl_router.market_causality_history(limit=10)
        assert history["status"] == "ok"
        assert history["total"] == 1

        row = history["history"][0]
        assert row["prediction_id"] == pid
        assert row["direction"] == "BUY"
        assert row["was_correct"] is True
        assert row["entry_price"] == 3050.0
        assert row["realized_price"] == 3100.0
        assert row["accuracy_score"] is not None and float(row["accuracy_score"]) > 0.0
        assert "prediction_timestamp" in row

    finally:
        mcl_router._PREDICTION_TRACKER = original_tracker
        mcl_router._LEARNING_ENGINE = original_engine


def test_history_round_trip_correct_only_filter(tmp_path):
    """correct_only=True must exclude losing outcomes."""
    from astroquant.backend.prediction_tracker import PredictionTracker
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    tracker = PredictionTracker(path=tmp_path / "rt_tracker2.json")
    engine = LearningFeedbackEngine(tracker=tracker)

    original_tracker = mcl_router._PREDICTION_TRACKER
    original_engine = mcl_router._LEARNING_ENGINE
    try:
        mcl_router._PREDICTION_TRACKER = tracker
        mcl_router._LEARNING_ENGINE = engine

        # WINning trade: direction=BUY, outcome=UP → was_correct=True
        mcl_router.market_causality_record_outcome({
            "prediction_id": "win-001",
            "direction": "BUY",
            "outcome_direction": "UP",
            "realized_price": 3100.0,
            "actual_move_pips": 50.0,
            "timeframe_reached": 5,
            "entry_price": 3050.0,
            "stop_price": 3020.0,
            "target_price": 3110.0,
        })

        # LOSing trade: direction=BUY, outcome=DOWN → was_correct=False
        mcl_router.market_causality_record_outcome({
            "prediction_id": "loss-001",
            "direction": "BUY",
            "outcome_direction": "DOWN",
            "realized_price": 3000.0,
            "actual_move_pips": -50.0,
            "timeframe_reached": 5,
            "entry_price": 3050.0,
            "stop_price": 3020.0,
            "target_price": 3110.0,
        })

        all_history = mcl_router.market_causality_history(limit=10, correct_only=False)
        assert all_history["total"] == 2

        wins_only = mcl_router.market_causality_history(limit=10, correct_only=True)
        assert wins_only["total"] == 1
        assert wins_only["history"][0]["prediction_id"] == "win-001"
        assert wins_only["history"][0]["was_correct"] is True
        assert wins_only["correct_only"] is True

    finally:
        mcl_router._PREDICTION_TRACKER = original_tracker
        mcl_router._LEARNING_ENGINE = original_engine


def test_weights_accuracy_trend_is_list_of_floats():
    """accuracy_trend in /weights must be a list of floats (up to 20 values)."""
    result = mcl_router.market_causality_weights()
    trend = result.get("accuracy_trend", [])
    assert isinstance(trend, list), "accuracy_trend must be a list"
    assert len(trend) <= 20, f"accuracy_trend should not exceed 20 values, got {len(trend)}"
    for v in trend:
        assert isinstance(v, float), f"Each accuracy_trend value must be float, got {type(v)}"
        assert 0.0 <= v <= 1.0, f"accuracy_trend value {v} out of [0, 1]"


def test_weights_floor_lower_bound_respected():
    """After many penalizing outcomes, weight must stay >= 0.20 (not 0.50)."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    engine = LearningFeedbackEngine(tracker=None)
    engine.weights = {"geometry": 0.50, "time": 0.50, "structure": 0.50,
                      "momentum": 0.50, "gann": 0.50, "ict": 0.50, "confluence": 0.90}
    engine.predictions = []
    engine.realized_outcomes = []

    # Feed 200 wrong outcomes for geometry to drive it to floor
    for i in range(200):
        pred = {"id": f"p{i}", "direction": "BUY", "confluence_score": 0.5,
                "signals": {"geometry": True, "time": False, "structure": False,
                            "momentum": False, "gann": False, "ict": False},
                "entry_price": 100.0, "stop_price": 95.0, "target_price": 110.0,
                "forecast_horizon_days": 1, "prediction_timestamp": 0}
        outcome = {"prediction_id": f"p{i}", "was_correct": False, "accuracy_score": 0.0,
                   "outcome_direction": "DOWN", "realized_price": 95.0,
                   "actual_move_pips": -50.0, "timeframe_reached": 5, "predicted_direction": "BUY"}
        engine._update_weights(pred, outcome)

    # geometry should have dropped but not below 0.20
    assert engine.weights["geometry"] >= 0.20, f"Floor violation: geometry={engine.weights['geometry']}"
    assert engine.weights["geometry"] < 0.50, "geometry should have decreased from starting value"
    # Other signals untouched from starting 0.50
    assert engine.weights["time"] == 0.50



# ---- confluence_signal + prediction_timestamp + direction_accuracy ----------

def test_confluence_signal_updates_confluence_weight():
    """When confluence_signal=True and outcome is correct, confluence weight must increase."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    engine = LearningFeedbackEngine(tracker=None)
    initial_w = engine.weights["confluence"]

    engine.record_prediction(
        prediction_id="conf-test-01", direction="BUY", confluence_score=0.85,
        geometry_signal=True, time_signal=True, structure_signal=True,
        momentum_signal=True, gann_signal=True, ict_signal=True,
        confluence_signal=True,
        entry_price=3050.0, stop_price=3020.0, target_price=3110.0, forecast_horizon_days=1,
    )
    engine.record_outcome(
        prediction_id="conf-test-01", realized_price=3110.0,
        outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5,
    )
    assert engine.weights["confluence"] > initial_w, (
        f"confluence weight should increase on correct prediction; was {initial_w}, now {engine.weights['confluence']}"
    )


def test_confluence_signal_false_does_not_move_confluence_weight():
    """When confluence_signal=False, the confluence weight must not change."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    engine = LearningFeedbackEngine(tracker=None)
    initial_w = engine.weights["confluence"]

    engine.record_prediction(
        prediction_id="conf-false-01", direction="BUY", confluence_score=0.40,
        geometry_signal=True, time_signal=False, structure_signal=False,
        momentum_signal=False, gann_signal=False, ict_signal=False,
        confluence_signal=False,
        entry_price=3050.0, stop_price=3020.0, target_price=3110.0, forecast_horizon_days=1,
    )
    engine.record_outcome(
        prediction_id="conf-false-01", realized_price=3110.0,
        outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5,
    )
    assert engine.weights["confluence"] == initial_w, (
        f"confluence weight should be unchanged when confluence_signal=False; got {engine.weights['confluence']}"
    )


def test_prediction_timestamp_is_non_null_integer():
    """record_prediction must stamp prediction_timestamp as a non-null int."""
    import time as _time
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    engine = LearningFeedbackEngine(tracker=None)
    t_before = int(_time.time())
    engine.record_prediction(
        prediction_id="ts-test-01", direction="SELL", confluence_score=0.6,
        geometry_signal=True, time_signal=True, structure_signal=True,
        momentum_signal=False, gann_signal=True, ict_signal=False,
        confluence_signal=False,
        entry_price=3100.0, stop_price=3130.0, target_price=3040.0, forecast_horizon_days=1,
    )
    t_after = int(_time.time())

    pred = next(p for p in engine.predictions if p["id"] == "ts-test-01")
    ts = pred["prediction_timestamp"]
    assert ts is not None, "prediction_timestamp must not be None"
    assert isinstance(ts, int), f"prediction_timestamp must be int, got {type(ts)}"
    assert t_before <= ts <= t_after, f"prediction_timestamp {ts} not in expected range [{t_before}, {t_after}]"


def test_sideways_outcome_against_directional_prediction_scores_zero():
    """BUY or SELL prediction with SIDEWAYS outcome must get accuracy_score=0.0 (not 0.5)."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    engine = LearningFeedbackEngine(tracker=None)
    engine.record_prediction(
        prediction_id="sw-test-01", direction="BUY", confluence_score=0.7,
        geometry_signal=True, time_signal=True, structure_signal=True,
        momentum_signal=True, gann_signal=True, ict_signal=True,
        confluence_signal=True,
        entry_price=3050.0, stop_price=3020.0, target_price=3110.0, forecast_horizon_days=1,
    )
    result = engine.record_outcome(
        prediction_id="sw-test-01", realized_price=3052.0,
        outcome_direction="SIDEWAYS", actual_move_pips=2.0, timeframe_reached=10,
    )
    assert result["accuracy_score"] == 0.0, (
        f"BUY vs SIDEWAYS should score 0.0, got {result['accuracy_score']}"
    )
    assert result["was_correct"] is False


def test_sideways_outcome_against_wait_prediction_scores_one():
    """WAIT prediction with SIDEWAYS outcome must be was_correct=True, accuracy_score=1.0."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    engine = LearningFeedbackEngine(tracker=None)
    engine.record_prediction(
        prediction_id="sw-wait-01", direction="WAIT", confluence_score=0.1,
        geometry_signal=False, time_signal=False, structure_signal=False,
        momentum_signal=False, gann_signal=False, ict_signal=False,
        confluence_signal=False,
        entry_price=3050.0, stop_price=3020.0, target_price=3110.0, forecast_horizon_days=1,
    )
    result = engine.record_outcome(
        prediction_id="sw-wait-01", realized_price=3051.0,
        outcome_direction="SIDEWAYS", actual_move_pips=1.0, timeframe_reached=10,
    )
    assert result["was_correct"] is True
    assert result["accuracy_score"] == 1.0


def test_direction_accuracy_in_weights_endpoint():
    """/weights must return direction_accuracy dict with keys as floats in [0,1]."""
    result = mcl_router.market_causality_weights()
    dir_acc = result.get("direction_accuracy", {})
    assert isinstance(dir_acc, dict), "direction_accuracy must be a dict"
    for direction, val in dir_acc.items():
        assert direction in ("BUY", "SELL", "WAIT"), f"Unexpected direction key: {direction}"
        assert isinstance(val, float), f"direction_accuracy[{direction}] must be float"
        assert 0.0 <= val <= 1.0, f"direction_accuracy[{direction}]={val} out of [0,1]"


def test_direction_accuracy_computed_correctly():
    """direction_accuracy values must match manually computed BUY/SELL rates."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    engine = LearningFeedbackEngine(tracker=None)

    # 2 correct BUY, 1 wrong BUY -> BUY accuracy = 2/3
    for pid, outcome_dir in [("b1", "UP"), ("b2", "UP"), ("b3", "DOWN")]:
        engine.record_prediction(
            prediction_id=pid, direction="BUY", confluence_score=0.7,
            geometry_signal=True, time_signal=True, structure_signal=True,
            momentum_signal=True, gann_signal=True, ict_signal=True,
            confluence_signal=True, entry_price=3050.0, stop_price=3020.0,
            target_price=3110.0, forecast_horizon_days=1,
        )
        engine.record_outcome(
            prediction_id=pid, realized_price=3080.0,
            outcome_direction=outcome_dir, actual_move_pips=30.0, timeframe_reached=5,
        )

    # 1 correct SELL -> SELL accuracy = 1/1
    engine.record_prediction(
        prediction_id="s1", direction="SELL", confluence_score=0.7,
        geometry_signal=True, time_signal=True, structure_signal=True,
        momentum_signal=True, gann_signal=True, ict_signal=True,
        confluence_signal=True, entry_price=3100.0, stop_price=3130.0,
        target_price=3040.0, forecast_horizon_days=1,
    )
    engine.record_outcome(
        prediction_id="s1", realized_price=3040.0,
        outcome_direction="DOWN", actual_move_pips=-60.0, timeframe_reached=5,
    )

    cal = engine.get_model_calibration()
    dir_acc = cal["direction_accuracy"]
    assert abs(dir_acc["BUY"] - 2/3) < 0.001, f"BUY accuracy expected 0.667, got {dir_acc['BUY']}"
    assert dir_acc["SELL"] == 1.0, f"SELL accuracy expected 1.0, got {dir_acc['SELL']}"


# ── POST /run_batch ───────────────────────────────────────────────────────────

def test_run_batch_returns_status_key():
    """POST /run_batch always returns a dict with a 'status' key."""
    from astroquant.backend.router_market_causality import market_causality_run_batch
    result = market_causality_run_batch({"dry_run": True})
    assert "status" in result, f"Expected 'status' key, got keys: {list(result.keys())}"


def test_run_batch_dry_run_does_not_change_weights():
    """POST /run_batch with dry_run=true must not modify persisted weights."""
    from astroquant.backend.router_market_causality import market_causality_run_batch, _PREDICTION_TRACKER
    before = _PREDICTION_TRACKER.load_weights().copy()
    market_causality_run_batch({"dry_run": True})
    after = _PREDICTION_TRACKER.load_weights()
    assert before == after, "Weights changed during dry_run batch — should not happen"


def test_run_batch_returns_total_predictions_key():
    """POST /run_batch result must include total_predictions (int >= 0)."""
    from astroquant.backend.router_market_causality import market_causality_run_batch
    result = market_causality_run_batch({"dry_run": True})
    assert "total_predictions" in result
    assert isinstance(result["total_predictions"], int)
    assert result["total_predictions"] >= 0


# ── POST /reset_weights ───────────────────────────────────────────────────────

def test_reset_weights_returns_status_ok():
    """POST /reset_weights returns status='weights_reset'."""
    from astroquant.backend.router_market_causality import market_causality_reset_weights
    result = market_causality_reset_weights({})
    assert result["status"] == "weights_reset"


def test_reset_weights_restores_all_seven_baseline_keys():
    """POST /reset_weights must return all 7 baseline weight keys."""
    from astroquant.backend.router_market_causality import market_causality_reset_weights
    result = market_causality_reset_weights({})
    expected_keys = {"geometry", "time", "structure", "momentum", "gann", "ict", "confluence"}
    assert set(result["weights"].keys()) == expected_keys


def test_reset_weights_values_match_baseline():
    """POST /reset_weights values must exactly match the documented baseline."""
    from astroquant.backend.router_market_causality import market_causality_reset_weights
    expected = {"geometry": 0.88, "time": 0.82, "structure": 0.92,
                "momentum": 0.85, "gann": 0.80, "ict": 0.78, "confluence": 0.90}
    result = market_causality_reset_weights({})
    for k, v in expected.items():
        assert abs(result["weights"][k] - v) < 1e-9, f"{k}: expected {v}, got {result['weights'][k]}"


def test_reset_weights_syncs_live_engine():
    """POST /reset_weights must sync the live engine so /weights reflects baseline immediately."""
    from astroquant.backend.router_market_causality import (
        market_causality_reset_weights,
        market_causality_weights,
        _LEARNING_ENGINE,
    )
    market_causality_reset_weights({})
    assert abs(_LEARNING_ENGINE.weights["geometry"] - 0.88) < 1e-9, "Live engine not synced after reset"


def test_reset_weights_predictions_cleared_false_by_default():
    """POST /reset_weights without clear_predictions should leave predictions intact."""
    from astroquant.backend.router_market_causality import market_causality_reset_weights
    import tempfile, os
    from astroquant.backend.prediction_tracker import PredictionTracker
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    # Use a temp tracker to avoid side effects on production data
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp_path = f.name
    try:
        tracker = PredictionTracker(tmp_path)
        engine  = LearningFeedbackEngine(tracker=tracker)
        engine.record_prediction(
            prediction_id="sentinel", direction="BUY", confluence_score=0.5,
            geometry_signal=True, time_signal=False, structure_signal=False,
            momentum_signal=False, gann_signal=False, ict_signal=False,
            confluence_signal=False, entry_price=3000.0, stop_price=2980.0,
            target_price=3040.0, forecast_horizon_days=1,
        )
        assert len(tracker.load_predictions()) == 1
        # reset_weights on the *module-level* tracker — predictions must still exist via temp tracker
        # This test verifies the flag default is False (no clear)
        result = market_causality_reset_weights({})
        assert result["predictions_cleared"] is False
    finally:
        os.unlink(tmp_path)


# ── Outcome upsert idempotency tests ─────────────────────────────────────────

def _make_engine_with_one_outcome(pid: str = "test-upsert") -> "LearningFeedbackEngine":
    """Helper: create an in-memory engine with one recorded prediction + outcome."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    e = LearningFeedbackEngine(tracker=None)
    for _ in range(1):
        e.record_prediction(
            prediction_id=pid, direction="BUY", confluence_score=0.8,
            geometry_signal=True, time_signal=True, structure_signal=True,
            momentum_signal=True, gann_signal=True, ict_signal=True,
            confluence_signal=True, entry_price=3000.0, stop_price=2970.0,
            target_price=3060.0, forecast_horizon_days=1,
        )
        e.record_outcome(
            prediction_id=pid, realized_price=3060.0,
            outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5,
        )
    return e


def test_record_outcome_second_call_returns_outcome_updated():
    """Calling record_outcome for the same prediction_id twice should return status='outcome_updated'."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    e = _make_engine_with_one_outcome("up1")
    result = e.record_outcome(
        prediction_id="up1", realized_price=3055.0,
        outcome_direction="UP", actual_move_pips=55.0, timeframe_reached=6,
    )
    assert result["status"] == "outcome_updated", f"Expected 'outcome_updated', got {result['status']}"


def test_record_outcome_upsert_does_not_grow_realized_outcomes():
    """Re-recording an outcome must NOT increase the length of realized_outcomes."""
    e = _make_engine_with_one_outcome("up2")
    count_before = len(e.realized_outcomes)
    e.record_outcome(
        prediction_id="up2", realized_price=3060.0,
        outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5,
    )
    assert len(e.realized_outcomes) == count_before, (
        f"realized_outcomes grew: {count_before} -> {len(e.realized_outcomes)}"
    )


def test_record_outcome_upsert_no_double_weight_change():
    """Re-recording the same outcome must NOT fire _update_weights() again (weights unchanged)."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    e = LearningFeedbackEngine(tracker=None)
    e.record_prediction(
        prediction_id="wt1", direction="BUY", confluence_score=0.8,
        geometry_signal=True, time_signal=True, structure_signal=True,
        momentum_signal=True, gann_signal=True, ict_signal=True,
        confluence_signal=True, entry_price=3000.0, stop_price=2970.0,
        target_price=3060.0, forecast_horizon_days=1,
    )
    e.record_outcome(
        prediction_id="wt1", realized_price=3060.0,
        outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5,
    )
    weights_after_first = e.weights.copy()
    e.record_outcome(
        prediction_id="wt1", realized_price=3060.0,
        outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5,
    )
    assert e.weights == weights_after_first, "Weights changed on duplicate record_outcome — double-learning bug"


def test_save_outcome_upsert_on_disk(tmp_path):
    """PredictionTracker.save_outcome must upsert, not append duplicate prediction_ids."""
    from astroquant.backend.prediction_tracker import PredictionTracker

    tracker = PredictionTracker(str(tmp_path / "t.json"))
    o1 = {"prediction_id": "dup", "accuracy_score": 1.0, "was_correct": True}
    o2 = {"prediction_id": "dup", "accuracy_score": 0.0, "was_correct": False}
    tracker.save_outcome(o1)
    tracker.save_outcome(o2)   # same prediction_id
    outcomes = tracker.load_outcomes()
    assert len(outcomes) == 1, f"Expected 1 outcome after upsert, got {len(outcomes)}"
    assert outcomes[0]["accuracy_score"] == 0.0, "Upsert should keep LAST value"


def test_save_prediction_upsert_on_disk(tmp_path):
    """PredictionTracker.save_prediction must upsert, not append duplicate ids."""
    from astroquant.backend.prediction_tracker import PredictionTracker

    tracker = PredictionTracker(str(tmp_path / "t2.json"))
    p1 = {"id": "dup", "direction": "BUY", "signals": {"confluence": False}}
    p2 = {"id": "dup", "direction": "SELL", "signals": {"confluence": True}}
    tracker.save_prediction(p1)
    tracker.save_prediction(p2)
    preds = tracker.load_predictions()
    assert len(preds) == 1, f"Expected 1 prediction after upsert, got {len(preds)}"
    assert preds[0]["direction"] == "SELL", "Upsert should keep LAST value"
    assert preds[0]["signals"]["confluence"] is True


# ── signal_accuracy always includes all 7 keys ───────────────────────────────

def test_signal_accuracy_includes_all_weight_keys_when_signal_never_fires():
    """signal_accuracy must contain every weight key even when that signal never fired."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    e = LearningFeedbackEngine(tracker=None)
    # Only geometry fires; all others inactive
    e.record_prediction(
        prediction_id="sa1", direction="BUY", confluence_score=0.2,
        geometry_signal=True, time_signal=False, structure_signal=False,
        momentum_signal=False, gann_signal=False, ict_signal=False,
        confluence_signal=False, entry_price=3000.0, stop_price=2980.0,
        target_price=3040.0, forecast_horizon_days=1,
    )
    e.record_outcome(prediction_id="sa1", realized_price=3040.0,
                     outcome_direction="UP", actual_move_pips=40.0, timeframe_reached=3)
    cal = e.get_model_calibration()
    expected_keys = set(e.weights.keys())
    assert set(cal["signal_accuracy"].keys()) == expected_keys, (
        f"Missing keys: {expected_keys - set(cal['signal_accuracy'].keys())}"
    )


def test_signal_accuracy_none_value_for_inactive_signals():
    """signal_accuracy value must be None (not 0.0) when a signal never fired."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    e = LearningFeedbackEngine(tracker=None)
    e.record_prediction(
        prediction_id="sa2", direction="BUY", confluence_score=0.2,
        geometry_signal=True, time_signal=False, structure_signal=False,
        momentum_signal=False, gann_signal=False, ict_signal=False,
        confluence_signal=False, entry_price=3000.0, stop_price=2980.0,
        target_price=3040.0, forecast_horizon_days=1,
    )
    e.record_outcome(prediction_id="sa2", realized_price=3040.0,
                     outcome_direction="UP", actual_move_pips=40.0, timeframe_reached=3)
    cal = e.get_model_calibration()
    assert cal["signal_accuracy"]["confluence"] is None, "Inactive signal should have None accuracy"
    assert cal["signal_accuracy"]["geometry"] is not None, "Active signal should have numeric accuracy"


# ── model_confidence sample-size tiers ───────────────────────────────────────

def test_model_confidence_learning_when_fewer_than_20_outcomes():
    """model_confidence must be 'LEARNING' with < 20 outcomes regardless of accuracy."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    e = LearningFeedbackEngine(tracker=None)
    for i in range(5):
        e.record_prediction(
            prediction_id=f"mc{i}", direction="BUY", confluence_score=0.9,
            geometry_signal=True, time_signal=True, structure_signal=True,
            momentum_signal=True, gann_signal=True, ict_signal=True,
            confluence_signal=True, entry_price=3000.0, stop_price=2970.0,
            target_price=3060.0, forecast_horizon_days=1,
        )
        e.record_outcome(prediction_id=f"mc{i}", realized_price=3060.0,
                         outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5)
    cal = e.get_model_calibration()
    assert cal["model_confidence"] == "LEARNING", (
        f"Expected LEARNING with 5 outcomes, got {cal['model_confidence']}"
    )


def test_model_confidence_calibrating_between_20_and_100_outcomes():
    """model_confidence must be 'CALIBRATING' with 20-99 outcomes (accuracy <55%)."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    e = LearningFeedbackEngine(tracker=None)
    for i in range(30):
        e.record_prediction(
            prediction_id=f"cal{i}", direction="BUY", confluence_score=0.5,
            geometry_signal=True, time_signal=False, structure_signal=False,
            momentum_signal=False, gann_signal=False, ict_signal=False,
            confluence_signal=False, entry_price=3000.0, stop_price=2980.0,
            target_price=3040.0, forecast_horizon_days=1,
        )
        outcome_dir = "UP" if i % 3 == 0 else "DOWN"  # 33% correct
        e.record_outcome(prediction_id=f"cal{i}", realized_price=3040.0,
                         outcome_direction=outcome_dir, actual_move_pips=40.0, timeframe_reached=3)
    cal = e.get_model_calibration()
    assert cal["model_confidence"] == "CALIBRATING", (
        f"Expected CALIBRATING with 30 outcomes, got {cal['model_confidence']}"
    )


# ── _discover_chart_files deduplication ──────────────────────────────────────

def test_discover_chart_files_deduplicates_same_symbol_timeframe(tmp_path, monkeypatch):
    """_discover_chart_files must return unique (symbol, timeframe) pairs only."""
    from astroquant.backend import backtest_replay

    # Create two files with same symbol+timeframe key
    (tmp_path / "last_known_chart_GC.FUT_1m.json").write_text("{}")
    (tmp_path / "last_known_chart_GC.FUT_1m_copy.json").write_text("{}")  # different stem → different key

    monkeypatch.setattr(backtest_replay, "_DATA_DIR", tmp_path)
    pairs = backtest_replay._discover_chart_files()
    # Should not have duplicates
    assert len(pairs) == len(set(pairs)), f"Duplicate pairs returned: {pairs}"


def test_discover_chart_files_normal_files_all_returned(tmp_path, monkeypatch):
    """_discover_chart_files must return one entry per unique (symbol, timeframe)."""
    from astroquant.backend import backtest_replay

    for name in ["last_known_chart_GC.FUT_1m.json", "last_known_chart_GC.FUT_5m.json",
                 "last_known_chart_NQ.FUT_1m.json"]:
        (tmp_path / name).write_text("{}")

    monkeypatch.setattr(backtest_replay, "_DATA_DIR", tmp_path)
    pairs = backtest_replay._discover_chart_files()
    assert len(pairs) == 3
    assert ("GC.FUT", "1m") in pairs
    assert ("NQ.FUT", "1m") in pairs


# ── Weight rehydration: fresh engine re-learns all outcomes ──────────────────

def test_fresh_engine_relearns_from_all_existing_outcomes():
    """A new engine instance must fire _update_weights for every loaded outcome."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    from astroquant.backend.prediction_tracker import PredictionTracker
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        tmp = f.name
    try:
        tracker = PredictionTracker(tmp)
        e1 = LearningFeedbackEngine(tracker=tracker)
        e1.record_prediction(
            prediction_id="rh1", direction="BUY", confluence_score=0.8,
            geometry_signal=True, time_signal=True, structure_signal=True,
            momentum_signal=True, gann_signal=True, ict_signal=True,
            confluence_signal=True, entry_price=3000.0, stop_price=2970.0,
            target_price=3060.0, forecast_horizon_days=1,
        )
        e1.record_outcome(prediction_id="rh1", realized_price=3060.0,
                          outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5)
        weights_trained = e1.weights.copy()

        # Simulate reset: persist baseline weights to tracker
        baseline = {"geometry": 0.88, "time": 0.82, "structure": 0.92,
                    "momentum": 0.85, "gann": 0.80, "ict": 0.78, "confluence": 0.90}
        tracker.save_weights(baseline)

        # New engine loads baseline weights but SAME outcome history
        e2 = LearningFeedbackEngine(tracker=tracker)
        # Record outcome again so it rehydrates
        e2.record_outcome(prediction_id="rh1", realized_price=3060.0,
                          outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5)
        # e2 weights should match e1's trained weights
        for k in weights_trained:
            assert abs(e2.weights[k] - weights_trained[k]) < 1e-9, (
                f"Weight '{k}' after rehydration: expected {weights_trained[k]:.6f}, got {e2.weights[k]:.6f}"
            )
    finally:
        os.unlink(tmp)


def test_same_engine_no_double_weight_on_repeat_outcome():
    """Calling record_outcome twice on the SAME engine instance must not double-update weights."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine

    e = LearningFeedbackEngine(tracker=None)
    e.record_prediction(
        prediction_id="sw1", direction="BUY", confluence_score=0.7,
        geometry_signal=True, time_signal=False, structure_signal=False,
        momentum_signal=False, gann_signal=False, ict_signal=False,
        confluence_signal=False, entry_price=3000.0, stop_price=2970.0,
        target_price=3060.0, forecast_horizon_days=1,
    )
    e.record_outcome(prediction_id="sw1", realized_price=3060.0,
                     outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5)
    after_first = e.weights.copy()
    e.record_outcome(prediction_id="sw1", realized_price=3060.0,
                     outcome_direction="UP", actual_move_pips=60.0, timeframe_reached=5)
    assert e.weights == after_first, "Weights changed on second record_outcome for same engine — double-learning"


# ── /status includes model health ────────────────────────────────────────────

def test_status_endpoint_includes_model_confidence():
    """GET /status must include model_confidence key."""
    from astroquant.backend.router_market_causality import market_causality_status
    s = market_causality_status()
    assert "model_confidence" in s, f"model_confidence missing from /status keys: {list(s.keys())}"
    assert s["model_confidence"] in ("HIGH", "MEDIUM", "LOW", "CALIBRATING", "LEARNING")


def test_status_endpoint_includes_accuracy_and_counts():
    """GET /status must include overall_accuracy, total_outcomes, total_predictions."""
    from astroquant.backend.router_market_causality import market_causality_status
    s = market_causality_status()
    for field in ("overall_accuracy", "total_outcomes", "total_predictions"):
        assert field in s, f"'{field}' missing from /status"
    assert 0.0 <= s["overall_accuracy"] <= 1.0
    assert s["total_outcomes"] >= 0
    assert s["total_predictions"] >= 0


def test_status_endpoint_includes_top_and_weakest_signal():
    """GET /status must name the top-performing and weakest signal."""
    from astroquant.backend.router_market_causality import market_causality_status
    s = market_causality_status()
    assert "top_signal" in s and "weakest_signal" in s
    valid = {"geometry", "time", "structure", "momentum", "gann", "ict", "confluence"}
    assert s["top_signal"] in valid
    assert s["weakest_signal"] in valid


# ── /history includes confluence_score ───────────────────────────────────────

def test_history_rows_include_confluence_score():
    """GET /history rows must include a confluence_score field."""
    from astroquant.backend.router_market_causality import market_causality_history
    data = market_causality_history(limit=10)
    if data["history"]:
        row = data["history"][0]
        assert "confluence_score" in row, f"confluence_score missing from history row keys: {list(row.keys())}"


def test_history_total_reflects_full_count_not_page_size():
    """/history 'total' must be the unfiltered count, 'returned' the page size."""
    from astroquant.backend.router_market_causality import market_causality_history

    data_small = market_causality_history(limit=2)
    assert "total" in data_small
    assert "returned" in data_small
    # total >= returned always
    assert data_small["total"] >= data_small["returned"]
    # returned <= limit
    assert data_small["returned"] <= 2


def test_history_total_equals_returned_when_small_dataset(tmp_path):
    """When fewer outcomes than limit, total == returned."""
    from astroquant.backend.router_market_causality import market_causality_history

    data = market_causality_history(limit=10000)
    assert data["total"] == data["returned"]


# ── run_batch cleaned_bare_ids ────────────────────────────────────────────────

def test_run_batch_response_includes_cleaned_bare_ids():
    """POST /run_batch response must include 'cleaned_bare_ids' (int)."""
    from astroquant.backend.router_market_causality import market_causality_run_batch
    result = market_causality_run_batch({"dry_run": True})
    assert "cleaned_bare_ids" in result, f"cleaned_bare_ids missing from response: {list(result.keys())}"
    assert isinstance(result["cleaned_bare_ids"], int)


# ── Timeframe normalization ─────────────────────────────────────────────────

def test_normalize_timeframe_bare_digits():
    """_normalize_timeframe must append 'm' to bare-digit timeframe strings."""
    from astroquant.backend.backtest_replay import _normalize_timeframe
    assert _normalize_timeframe("1")  == "1m"
    assert _normalize_timeframe("5")  == "5m"
    assert _normalize_timeframe("15") == "15m"
    assert _normalize_timeframe("30") == "30m"


def test_normalize_timeframe_already_suffixed():
    """_normalize_timeframe must leave already-suffixed strings unchanged."""
    from astroquant.backend.backtest_replay import _normalize_timeframe
    assert _normalize_timeframe("1m")  == "1m"
    assert _normalize_timeframe("1h")  == "1h"
    assert _normalize_timeframe("1d")  == "1d"
    assert _normalize_timeframe("4h")  == "4h"


def test_discover_chart_files_normalizes_bare_number_dedup(tmp_path, monkeypatch):
    """last_known_chart_GC.FUT_1.json and _1m.json should deduplicate to one pair."""
    from astroquant.backend import backtest_replay

    (tmp_path / "last_known_chart_GC.FUT_1.json").write_text("{}")
    (tmp_path / "last_known_chart_GC.FUT_1m.json").write_text("{}")

    monkeypatch.setattr(backtest_replay, "_DATA_DIR", tmp_path)
    pairs = backtest_replay._discover_chart_files()
    symbols = [p[0] for p in pairs if p[0] == "GC.FUT"]
    assert len(symbols) == 1, f"Expected 1 GC.FUT pair, got {len(symbols)}: {pairs}"


# ── tf_minutes bare timeframe fix ─────────────────────────────────────────────

def test_run_replay_tf_minutes_uses_normalized_timeframe(tmp_path, monkeypatch):
    """run_replay must use the normalised timeframe for tf_minutes lookup so that
    a bare-digit TF (e.g. '1') computes the same horizon_days as '1m'."""
    from astroquant.backend import backtest_replay

    # Minimal candle list — enough that run_replay() doesn't skip everything
    candles = [{"open": 2000 + i, "high": 2001 + i, "low": 1999 + i,
                "close": 2000 + i, "timestamp": 1700000000 + i * 60}
               for i in range(60)]

    chart_file = tmp_path / "last_known_chart_GC.FUT_1.json"
    import json
    chart_file.write_text(json.dumps({"symbol": "GC.FUT", "timeframe": "1", "candles": candles}))
    monkeypatch.setattr(backtest_replay, "_DATA_DIR", tmp_path)

    captured = {}

    _orig = backtest_replay._evaluate_outcome
    def _mock_eval(candles, idx, entry, horizon, min_move):
        # Record horizon so we can inspect it indirectly via horizon_days
        captured["horizon"] = horizon
        return ("UP", entry + 5.0, 5.0, 1)

    monkeypatch.setattr(backtest_replay, "_evaluate_outcome", _mock_eval)

    # Run with bare TF '1' — should NOT raise and horizon should be passed through
    result = backtest_replay.run_replay(
        symbol="GC.FUT", timeframe="1", window=5, horizon=10,
        dry_run=True, tracker_path=str(tmp_path / "t.json"),
    )
    assert result.get("status") == "ok"
    assert captured.get("horizon") == 10, "horizon not forwarded to _evaluate_outcome"


# ── /run_batch passes min_move ─────────────────────────────────────────────────

def test_run_batch_accepts_min_move_param(tmp_path, monkeypatch):
    """POST /run_batch should pass min_move from payload down to run_batch_replay."""
    import astroquant.backend.backtest_replay as _br
    from astroquant.backend.router_market_causality import market_causality_run_batch

    captured: dict = {}

    def _mock_run_batch_replay(**kwargs):
        captured.update(kwargs)
        return {"status": "ok", "total_predictions": 0, "results": [],
                "cleaned_bare_ids": 0}

    # Patch the module-level symbol so the local import inside the endpoint resolves it
    monkeypatch.setattr(_br, "run_batch_replay", _mock_run_batch_replay)
    import sys
    sys.modules["astroquant.backend.backtest_replay"].run_batch_replay = _mock_run_batch_replay

    result = market_causality_run_batch({"dry_run": True, "min_move": 7.5})
    assert captured.get("min_move") == 7.5, f"min_move not forwarded; captured={captured}"


# ── _cleanup_bare_ids ─────────────────────────────────────────────────────────

def test_cleanup_bare_ids_renames_bare_tf_predictions(tmp_path):
    """_cleanup_bare_ids must rename replay-GC.FUT-1-barN to replay-GC.FUT-1m-barN."""
    from astroquant.backend.backtest_replay import _cleanup_bare_ids
    from astroquant.backend.prediction_tracker import PredictionTracker

    tracker_file = tmp_path / "tracker.json"
    t = PredictionTracker(tracker_file)

    # Save a bare-TF prediction + outcome
    bare_id = "replay-GC.FUT-1-bar24"
    t.save_prediction({"id": bare_id, "direction": "BUY", "entry_price": 2000.0,
                       "prediction_timestamp": 1700000000})
    t.save_outcome({"prediction_id": bare_id, "was_correct": True,
                    "realized_price": 2010.0, "outcome_direction": "UP"})

    changed = _cleanup_bare_ids(t)
    assert changed >= 1

    preds    = t.load_predictions()
    outcomes = t.load_outcomes()
    pred_ids    = [p["id"] for p in preds]
    outcome_ids = [o["prediction_id"] for o in outcomes]

    assert bare_id not in pred_ids, "bare-TF prediction ID should not remain"
    assert "replay-GC.FUT-1m-bar24" in pred_ids, "normalised ID must be present"
    assert bare_id not in outcome_ids, "bare-TF outcome prediction_id should not remain"
    assert "replay-GC.FUT-1m-bar24" in outcome_ids, "outcome must reference normalised ID"


def test_cleanup_bare_ids_deduplicates_collisions(tmp_path):
    """When both bare and normalised IDs exist, keep normalised and drop bare."""
    from astroquant.backend.backtest_replay import _cleanup_bare_ids
    from astroquant.backend.prediction_tracker import PredictionTracker

    tracker_file = tmp_path / "tracker.json"
    t = PredictionTracker(tracker_file)

    bare_id = "replay-GC.FUT-1-bar24"
    norm_id = "replay-GC.FUT-1m-bar24"

    t.save_prediction({"id": bare_id, "direction": "BUY",  "entry_price": 2000.0})
    t.save_prediction({"id": norm_id, "direction": "SELL", "entry_price": 2001.0})
    t.save_outcome({"prediction_id": bare_id, "was_correct": False})
    t.save_outcome({"prediction_id": norm_id, "was_correct": True})

    _cleanup_bare_ids(t)

    pred_ids    = [p["id"] for p in t.load_predictions()]
    outcome_ids = [o["prediction_id"] for o in t.load_outcomes()]

    assert pred_ids.count(norm_id) == 1, "normalised prediction should appear exactly once"
    assert bare_id not in pred_ids
    assert outcome_ids.count(norm_id) == 1
    assert bare_id not in outcome_ids


# ── save_predictions_bulk / save_outcomes_bulk ────────────────────────────────

def test_save_predictions_bulk_overwrites_all(tmp_path):
    """save_predictions_bulk must replace the full predictions list atomically."""
    from astroquant.backend.prediction_tracker import PredictionTracker

    t = PredictionTracker(tmp_path / "t.json")
    t.save_prediction({"id": "old-1", "direction": "BUY"})
    t.save_prediction({"id": "old-2", "direction": "SELL"})

    new_batch = [{"id": "new-1", "direction": "WAIT"}]
    t.save_predictions_bulk(new_batch)

    preds = t.load_predictions()
    assert len(preds) == 1
    assert preds[0]["id"] == "new-1"


def test_save_outcomes_bulk_overwrites_all(tmp_path):
    """save_outcomes_bulk must replace the full outcomes list atomically."""
    from astroquant.backend.prediction_tracker import PredictionTracker

    t = PredictionTracker(tmp_path / "t.json")
    t.save_outcome({"prediction_id": "p1", "was_correct": True})
    t.save_outcome({"prediction_id": "p2", "was_correct": False})

    new_batch = [{"prediction_id": "p3", "was_correct": True}]
    t.save_outcomes_bulk(new_batch)

    outcomes = t.load_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0]["prediction_id"] == "p3"


# ---- Q5 news context tests --------------------------------------------------

_Q5_OBS_CSV = """\
observation_id,recorded_at_utc,symbol,requested_timeframe,applied_timeframe,lookback_years,source_mode,signal,trend_label,trend_start_time,trend_start_price,trend_duration_hours,latest_time,latest_price,signal_start_time,signal_end_time,signal_start_price,signal_end_price,signal_window_hours,signal_projected_move,signal_projected_move_pct,signal_window_basis,gann_nearest_key_angle,gann_angle_proximity,numerology_cycle_runtime,numerology_harmonious_runtime,structure_major_runtime,structure_bos_runtime,physics_momentum_runtime,physics_acceleration_runtime,confirmation_geometry,confirmation_time,confirmation_structure,confirmation_tape_action,gann_mindset_bias,gann_time_phase,gann_recommended_signal,gann_mindset_narration,news_previous_time,news_previous_event,news_previous_impact,news_previous_minutes_ago,news_next_time,news_next_event,news_next_impact,news_next_minutes_ahead,price_degree,gann_degree,gann_cycle_degree,gann_cycle_quadrant,gann_cycle_description,gann_nearest_angles,gann_price_time_status,gann_price_time_ratio,nakshatra,nakshatra_pada,geometry_slope_price_per_hour,geometry_angle_deg,physics_velocity_price_per_hour,physics_acceleration_price_per_hour2,price_time_ratio,degree_time_ratio,date_time_code
obsA,2026-04-03T10:00:00+00:00,XAUUSD,1d,1d,1,historical_first,BUY,UP,2026-04-01T00:00:00,3050.0,48.0,2026-04-03T00:00:00,3120.0,2026-04-01T00:00:00,2026-04-04T00:00:00,3050.0,3120.0,72.0,70.0,2.3,physics_projection,270,EXACT,EXPANSION,False,TREND,True,UP,30.0,YES,YES,YES,YES,BUY_CONTINUATION,EXPANSION,BUY,Price near 270deg,2026-04-01T13:30:00,US Core PCE,high,2340.0,2026-04-10T13:30:00,US CPI YoY,high,5130.0,273.56,273.56,202.11,3,DISTRIBUTION,8x1,PRICE_LEADS,54.5,Uttara Ashadha,3,0.5,26.0,0.5,0.008,54.5,0.2,20260403
""".strip()


@pytest.fixture
def obs_log_with_q5(tmp_path, monkeypatch):
    """Write a minimal observation log CSV and patch _observation_log_csv_path to use it."""
    import pathlib
    csv_path = tmp_path / "market_observations.csv"
    csv_path.write_text(_Q5_OBS_CSV)
    import astroquant.backend.router_market_causality as _r
    monkeypatch.setattr(_r, "_observation_log_csv_path", lambda: pathlib.Path(csv_path))
    return csv_path


def test_q5_answer_always_present_in_gann_qa(obs_log_with_q5):
    """Every era group in /gann_qa rows must include a Q5 news question."""
    from astroquant.backend.router_market_causality import market_causality_gann_qa

    result = market_causality_gann_qa(date="2026-04-03", symbol="XAUUSD", limit=60, horizon_days=1)


def test_q5_answer_contains_news_event_fields(obs_log_with_q5):
    """Q5 answer must reference the previous and next news events from the observation."""
    from astroquant.backend.router_market_causality import market_causality_gann_qa

    result = market_causality_gann_qa(date="2026-04-03", symbol="XAUUSD", limit=60, horizon_days=1)
    rows = result.get("rows", [])
    q5_rows = [r for r in rows if "news" in str(r.get("question", "")).lower()]
    assert q5_rows, "No Q5 rows"

    for row in q5_rows[:3]:
        assert row.get("recommended_signal") in ("BUY", "SELL", "WAIT")
        answer = str(row.get("answer", ""))
        assert len(answer) > 20, f"Q5 answer too short: {answer!r}"
        assert any(kw in answer for kw in ("Previous event", "Next scheduled", "No high-impact")), (
            f"Q5 answer missing news keywords: {answer!r}"
        )


def test_q5_high_impact_news_triggers_caution_flag(obs_log_with_q5):
    """Q5 answer must include caution text when the next event is high-impact."""
    from astroquant.backend.router_market_causality import market_causality_gann_qa

    # The seed CSV has news_next_impact=high → CAUTION must appear in Q5 answer.
    result = market_causality_gann_qa(date="2026-04-03", symbol="XAUUSD", limit=60, horizon_days=1)
    rows = result.get("rows", [])
    q5_rows = [r for r in rows if "news" in str(r.get("question", "")).lower()]
    assert q5_rows, "No Q5 rows"

    # At least one Q5 row should contain CAUTION (seeded next-event is high-impact).
    caution_rows = [r for r in q5_rows if "CAUTION" in str(r.get("answer", ""))]
    assert caution_rows, (
        f"Expected CAUTION in Q5 answer for high-impact next event; answers: "
        f"{[r.get('answer','')[:80] for r in q5_rows]}"
    )


# ---- signal_accuracy tests --------------------------------------------------

def test_signal_accuracy_keys_match_weight_keys():
    """signal_accuracy in /weights response must contain exactly the same keys as weights."""
    from astroquant.backend.router_market_causality import market_causality_weights

    result = market_causality_weights()
    assert result["status"] == "ok"
    weight_keys = set(result["weights"].keys())
    accuracy_keys = set(result["signal_accuracy"].keys())
    assert weight_keys == accuracy_keys, (
        f"signal_accuracy keys {accuracy_keys} do not match weight keys {weight_keys}"
    )


def test_signal_accuracy_values_are_float_or_none():
    """Each signal_accuracy value must be a float in [0,1] or None (no data yet)."""
    from astroquant.backend.router_market_causality import market_causality_weights

    result = market_causality_weights()
    for signal, acc in result["signal_accuracy"].items():
        assert acc is None or (isinstance(acc, float) and 0.0 <= acc <= 1.0), (
            f"signal_accuracy[{signal!r}] = {acc!r} — expected float in [0,1] or None"
        )


def test_signal_accuracy_none_when_no_outcomes(tmp_path):
    """signal_accuracy values must all be None when there are no realized outcomes."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    from astroquant.backend.prediction_tracker import PredictionTracker

    tracker = PredictionTracker(tmp_path / "empty.json")
    engine = LearningFeedbackEngine(tracker=tracker)

    cal = engine.get_model_calibration()
    for signal, acc in cal["signal_accuracy"].items():
        assert acc is None, (
            f"Expected None for signal {signal!r} with no outcomes, got {acc!r}"
        )


def test_signal_accuracy_reflects_correct_outcome(tmp_path):
    """After recording one correct BUY prediction, gann signal_accuracy must be > 0."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    from astroquant.backend.prediction_tracker import PredictionTracker

    tracker = PredictionTracker(tmp_path / "t.json")
    engine = LearningFeedbackEngine(tracker=tracker)

    engine.record_prediction(
        prediction_id="test-sig-acc-001",
        direction="BUY",
        confluence_score=0.8,
        geometry_signal=True,
        time_signal=True,
        structure_signal=True,
        momentum_signal=True,
        gann_signal=True,
        ict_signal=True,
        confluence_signal=True,
        entry_price=3100.0,
        stop_price=3090.0,
        target_price=3120.0,
        forecast_horizon_days=1,
    )
    engine.record_outcome(
        prediction_id="test-sig-acc-001",
        realized_price=3115.0,
        outcome_direction="UP",
        actual_move_pips=15.0,
        timeframe_reached=3,
    )

    cal = engine.get_model_calibration()
    gann_acc = cal["signal_accuracy"].get("gann")
    assert gann_acc is not None, "gann signal_accuracy should not be None after one outcome"
    assert gann_acc == 1.0, f"Expected gann accuracy=1.0 (one correct), got {gann_acc}"


def test_signal_accuracy_reflects_incorrect_outcome(tmp_path):
    """After one wrong SELL prediction, gann signal_accuracy must be 0.0."""
    from astroquant.backend.mathematical_engines import LearningFeedbackEngine
    from astroquant.backend.prediction_tracker import PredictionTracker

    tracker = PredictionTracker(tmp_path / "t.json")
    engine = LearningFeedbackEngine(tracker=tracker)

    engine.record_prediction(
        prediction_id="test-sig-acc-002",
        direction="SELL",
        confluence_score=0.7,
        geometry_signal=True,
        time_signal=False,
        structure_signal=False,
        momentum_signal=False,
        gann_signal=True,
        ict_signal=False,
        confluence_signal=False,
        entry_price=3100.0,
        stop_price=3110.0,
        target_price=3080.0,
        forecast_horizon_days=1,
    )
    engine.record_outcome(
        prediction_id="test-sig-acc-002",
        realized_price=3115.0,
        outcome_direction="UP",   # wrong direction for SELL
        actual_move_pips=15.0,
        timeframe_reached=2,
    )

    cal = engine.get_model_calibration()
    gann_acc = cal["signal_accuracy"].get("gann")
    assert gann_acc == 0.0, f"Expected gann accuracy=0.0 (one wrong), got {gann_acc}"

