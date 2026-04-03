from fastapi.testclient import TestClient

from astroquant.backend.main import app
import astroquant.backend.router_market_causality as mcl_router


def test_market_causality_summary_supports_25y_historical_contract():
    client = TestClient(app)

    response = client.get(
        "/market_causality/summary",
        params={
            "symbol": "XAUUSD",
            "timeframe": "1d",
            "lookback_years": 25,
            "source_mode": "historical_first",
            "refresh": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert "status" in payload
    assert payload.get("lookback_years") == 25
    assert payload.get("source_mode") == "historical_first"
    assert "rows_analyzed" in payload

    alignment = payload.get("instrument_alignment") or {}
    assert alignment.get("requested_symbol") == "XAUUSD"
    assert alignment.get("requested_timeframe") == "1d"
    assert alignment.get("requested_lookback_years") == 25
    assert alignment.get("requested_source_mode") == "historical_first"


def test_market_causality_summary_query_params_forwarded(monkeypatch):
    client = TestClient(app)
    seen = {}

    def _stub_compute_summary(refresh: bool, symbol: str, timeframe: str, lookback_years: int, source_mode: str):
        seen["refresh"] = refresh
        seen["symbol"] = symbol
        seen["timeframe"] = timeframe
        seen["lookback_years"] = lookback_years
        seen["source_mode"] = source_mode
        return {
            "status": "ok",
            "symbol": symbol,
            "requested_timeframe": timeframe,
            "lookback_years": lookback_years,
            "source_mode": source_mode,
        }

    monkeypatch.setattr(mcl_router, "_compute_summary", _stub_compute_summary)

    response = client.get(
        "/market_causality/summary",
        params={
            "refresh": "true",
            "symbol": "gc.fut",
            "timeframe": "15m",
            "lookback_years": 10,
            "source_mode": "live_first",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"

    assert seen["refresh"] is True
    assert seen["symbol"] == "gc.fut"
    assert seen["timeframe"] == "15m"
    assert seen["lookback_years"] == 10
    assert seen["source_mode"] == "live_first"


def test_market_causality_status_exposes_cache_metadata():
    client = TestClient(app)

    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()
    mcl_router._cache_payloads["XAUUSD|1m|25|historical_only"] = {"status": "ok"}
    mcl_router._cache_ts_by_key["XAUUSD|1m|25|historical_only"] = 1234.0

    response = client.get("/market_causality/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("cache_ttl_seconds") == 30.0
    assert payload.get("cache_entries") == 1
    assert payload.get("cache_keys") == ["XAUUSD|1m|25|historical_only"]


def test_market_causality_summary_rejects_invalid_lookback_years():
    client = TestClient(app)

    low = client.get(
        "/market_causality/summary",
        params={"lookback_years": 0},
    )
    high = client.get(
        "/market_causality/summary",
        params={"lookback_years": 101},
    )

    assert low.status_code == 422
    assert high.status_code == 422

    low_detail = low.json().get("detail") or []
    high_detail = high.json().get("detail") or []

    assert any(item.get("loc") == ["query", "lookback_years"] for item in low_detail)
    assert any(item.get("loc") == ["query", "lookback_years"] for item in high_detail)


def test_market_causality_status_reports_module_path_contract():
    client = TestClient(app)
    response = client.get("/market_causality/status")

    assert response.status_code == 200
    payload = response.json()
    module_path = payload.get("module_path")

    assert isinstance(module_path, str)
    assert module_path.endswith("market-causality-lab/main.py")
    assert payload.get("module_exists") is True


def test_market_causality_summary_normalizes_unsupported_source_mode(monkeypatch):
    client = TestClient(app)

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": "BUY",
                "source_mode": source_mode,
                "lookback_years": lookback_years,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "ok",
                    "chain": ["ok"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    response = client.get(
        "/market_causality/summary",
        params={
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "lookback_years": 25,
            "source_mode": "unsupported_mode",
            "refresh": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("source_mode") == "historical_first"

    alignment = payload.get("instrument_alignment") or {}
    assert alignment.get("requested_source_mode") == "historical_first"


def test_market_causality_summary_normalizes_symbol_and_timeframe(monkeypatch):
    client = TestClient(app)

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": "BUY",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "ok",
                    "chain": ["ok"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    response = client.get(
        "/market_causality/summary",
        params={
            "symbol": " gc.fut ",
            "timeframe": " 15M ",
            "lookback_years": 25,
            "source_mode": "historical_first",
            "refresh": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload.get("symbol") == "GC.FUT"
    assert payload.get("requested_timeframe") == "15m"

    alignment = payload.get("instrument_alignment") or {}
    assert alignment.get("requested_symbol") == "GC.FUT"
    assert alignment.get("requested_timeframe") == "15m"


def test_market_causality_status_cache_keys_are_sorted():
    client = TestClient(app)

    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()
    mcl_router._cache_payloads["XAUUSD|5m|25|historical_first"] = {"status": "ok"}
    mcl_router._cache_payloads["GC.FUT|1m|25|historical_only"] = {"status": "ok"}
    mcl_router._cache_payloads["XAUUSD|1d|25|historical_first"] = {"status": "ok"}

    response = client.get("/market_causality/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("cache_keys") == [
        "GC.FUT|1m|25|historical_only",
        "XAUUSD|1d|25|historical_first",
        "XAUUSD|5m|25|historical_first",
    ]


def test_market_causality_summary_uses_defaults_when_params_missing(monkeypatch):
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
                "applied_timeframe": timeframe,
                "filtered_signal": "BUY",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "defaults-ok",
                    "chain": ["defaults-ok"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    response = client.get("/market_causality/summary", params={"refresh": "true"})

    assert response.status_code == 200
    payload = response.json()
    assert payload.get("symbol") == "XAUUSD"
    assert payload.get("requested_timeframe") == "1d"
    assert payload.get("lookback_years") == 25
    assert payload.get("source_mode") == "historical_first"

    alignment = payload.get("instrument_alignment") or {}
    assert alignment.get("requested_symbol") == "XAUUSD"
    assert alignment.get("requested_timeframe") == "1d"
    assert alignment.get("requested_lookback_years") == 25
    assert alignment.get("requested_source_mode") == "historical_first"


def test_market_causality_timeframe_matrix_engine_stage_count_is_integer(monkeypatch):
    client = TestClient(app)

    def _stub_compute_summary(refresh: bool, symbol: str, timeframe: str, lookback_years: int, source_mode: str):
        return {
            "status": "ok",
            "signal": "BUY",
            "confidence": 0.75,
            "quality": "high",
            "requested_timeframe": timeframe,
            "applied_timeframe": timeframe,
            "timeframe_fallback_applied": False,
            "timeframe_fallback_reason": None,
            "rows_analyzed": 1000,
            "historical_depth_years": 25.0,
            "lookback_target_met": True,
            "lookback_depth_warning": None,
            "memory_size": 500,
            "process_timing": [{"name": "memory_probability_stack", "elapsed_ms": 10.5}],
            "ai_model_used": True,
            "ai_model_version": "test-model-v1",
            "ai_decision": {"signal": "BUY"},
            "reasoning_summary": "stub",
            "reasoning_top_drivers": [],
            "observation": {},
            "elapsed_ms": 12.34,
            "error": None,
            "news_status": "ok",
            "global_events_status": "ok",
        }

    monkeypatch.setattr(mcl_router, "_compute_summary", _stub_compute_summary)

    response = client.get(
        "/market_causality/timeframe_matrix",
        params={
            "symbol": "XAUUSD",
            "lookback_years": 25,
            "source_mode": "historical_first",
            "refresh": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    rows = payload.get("rows") or []
    assert len(rows) > 0
    assert all(isinstance(row.get("engine_stage_count"), int) for row in rows)
    assert all((row.get("engine_stage_count") or 0) >= 0 for row in rows)


def test_market_causality_summary_refresh_flag_controls_cache_reuse(monkeypatch):
    client = TestClient(app)
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
                "filtered_signal": f"API_SIGNAL_{calls['n']}",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "refresh-cache-check",
                    "chain": ["refresh-cache-check"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    first = client.get(
        "/market_causality/summary",
        params={"symbol": "XAUUSD", "timeframe": "1m", "source_mode": "historical_first", "refresh": "true"},
    )
    cached = client.get(
        "/market_causality/summary",
        params={"symbol": "XAUUSD", "timeframe": "1m", "source_mode": "historical_first", "refresh": "false"},
    )
    refreshed = client.get(
        "/market_causality/summary",
        params={"symbol": "XAUUSD", "timeframe": "1m", "source_mode": "historical_first", "refresh": "true"},
    )

    assert first.status_code == 200
    assert cached.status_code == 200
    assert refreshed.status_code == 200

    assert first.json().get("signal") == "API_SIGNAL_1"
    assert cached.json().get("signal") == "API_SIGNAL_1"
    assert refreshed.json().get("signal") == "API_SIGNAL_2"
    assert calls["n"] == 2


def test_market_causality_summary_surfaces_timeframe_fallback_fields(monkeypatch):
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
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "fallback-ok",
                    "chain": ["fallback-ok"],
                    "top_drivers": [],
                },
                "process_timing": [],
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
    assert payload.get("requested_timeframe") == "1m"
    assert payload.get("applied_timeframe") == "1h"
    assert payload.get("timeframe_fallback_applied") is True
    assert payload.get("timeframe_fallback_reason") == "requested_timeframe_depth_below_target"


def test_market_causality_summary_reasoning_delta_progression_across_refreshes(monkeypatch):
    client = TestClient(app)
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
                    "lookback_years": lookback_years,
                    "source_mode": source_mode,
                    "rows_analyzed": 1,
                    "reasoning_display": {
                        "tone": "bullish",
                        "summary": "first run",
                        "chain": ["first"],
                        "top_drivers": [{"label": "dominant_force", "score_pct": 70.0}],
                    },
                    "process_timing": [],
                }

            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": "SELL",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "bearish",
                    "summary": "second run",
                    "chain": ["second"],
                    "top_drivers": [{"label": "dominant_force", "score_pct": 40.0}],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    first = client.get(
        "/market_causality/summary",
        params={"symbol": "XAUUSD", "timeframe": "1m", "source_mode": "historical_first", "refresh": "true"},
    )
    second = client.get(
        "/market_causality/summary",
        params={"symbol": "XAUUSD", "timeframe": "1m", "source_mode": "historical_first", "refresh": "true"},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    p1 = first.json()
    p2 = second.json()

    assert p1.get("reasoning_delta", {}).get("has_previous") is False
    assert p2.get("reasoning_delta", {}).get("has_previous") is True
    assert p2.get("reasoning_delta", {}).get("previous_signal") == "BUY"
    assert p2.get("reasoning_delta", {}).get("signal_changed") is True


def test_market_causality_summary_reasoning_delta_top_driver_numeric_change(monkeypatch):
    client = TestClient(app)
    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()
    calls = {"n": 0}

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            calls["n"] += 1
            if calls["n"] == 1:
                drivers = [{"label": "dominant_force", "score_pct": 70.0}]
            else:
                drivers = [{"label": "dominant_force", "score_pct": 40.0}]

            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": "SELL" if calls["n"] > 1 else "BUY",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "delta-driver-check",
                    "chain": ["delta-driver-check"],
                    "top_drivers": drivers,
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    _ = client.get(
        "/market_causality/summary",
        params={"symbol": "XAUUSD", "timeframe": "1m", "source_mode": "historical_first", "refresh": "true"},
    )
    second = client.get(
        "/market_causality/summary",
        params={"symbol": "XAUUSD", "timeframe": "1m", "source_mode": "historical_first", "refresh": "true"},
    )

    assert second.status_code == 200
    delta = (second.json().get("reasoning_delta") or {}).get("top_driver_deltas") or []
    assert len(delta) >= 1
    assert delta[0].get("label") == "dominant_force"
    assert delta[0].get("previous_pct") == 70.0
    assert delta[0].get("current_pct") == 40.0
    assert delta[0].get("delta_pct") == -30.0


def test_market_causality_status_cache_entries_increase_after_new_summary_key(monkeypatch):
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
                "applied_timeframe": timeframe,
                "filtered_signal": "BUY",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "cache-entry-check",
                    "chain": ["cache-entry-check"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    before = client.get("/market_causality/status")
    assert before.status_code == 200
    assert before.json().get("cache_entries") == 0

    summary = client.get(
        "/market_causality/summary",
        params={
            "symbol": "GC.FUT",
            "timeframe": "5m",
            "lookback_years": 10,
            "source_mode": "historical_only",
            "refresh": "true",
        },
    )
    assert summary.status_code == 200

    after = client.get("/market_causality/status")
    assert after.status_code == 200
    payload = after.json()
    assert payload.get("cache_entries") == 1
    assert "GC.FUT|5m|10|historical_only" in (payload.get("cache_keys") or [])


def test_market_causality_summary_normalized_inputs_share_single_cache_key(monkeypatch):
    client = TestClient(app)
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
                "filtered_signal": "BUY",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "normalize-cache-key-check",
                    "chain": ["normalize-cache-key-check"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    monkeypatch.setattr(mcl_router, "_load_module", lambda: _DummyModule())

    first = client.get(
        "/market_causality/summary",
        params={
            "symbol": " gc.fut ",
            "timeframe": " 15M ",
            "lookback_years": 25,
            "source_mode": "historical_first",
            "refresh": "true",
        },
    )
    second = client.get(
        "/market_causality/summary",
        params={
            "symbol": "GC.FUT",
            "timeframe": "15m",
            "lookback_years": 25,
            "source_mode": "historical_first",
            "refresh": "false",
        },
    )
    status = client.get("/market_causality/status")

    assert first.status_code == 200
    assert second.status_code == 200
    assert status.status_code == 200
    assert calls["n"] == 1

    payload = status.json()
    assert payload.get("cache_entries") == 1
    assert payload.get("cache_keys") == ["GC.FUT|15m|25|historical_first"]


def test_market_causality_status_module_loaded_toggles_after_summary(monkeypatch):
    client = TestClient(app)
    mcl_router._cache_payloads.clear()
    mcl_router._cache_ts_by_key.clear()
    mcl_router._module = None

    class _DummyModule:
        @staticmethod
        def full_system(symbol: str, timeframe: str, lookback_years: int, source_mode: str):
            return {
                "data_source": "HISTORICAL CSV",
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "filtered_signal": "BUY",
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": 1,
                "reasoning_display": {
                    "tone": "neutral",
                    "summary": "module-loaded-check",
                    "chain": ["module-loaded-check"],
                    "top_drivers": [],
                },
                "process_timing": [],
            }

    def _stub_load_module():
        module = _DummyModule()
        mcl_router._module = module
        return module

    monkeypatch.setattr(mcl_router, "_load_module", _stub_load_module)

    before = client.get("/market_causality/status")
    assert before.status_code == 200
    assert before.json().get("module_loaded") is False

    summary = client.get(
        "/market_causality/summary",
        params={"symbol": "XAUUSD", "timeframe": "1m", "source_mode": "historical_first", "refresh": "true"},
    )
    assert summary.status_code == 200

    after = client.get("/market_causality/status")
    assert after.status_code == 200
    assert after.json().get("module_loaded") is True
