from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd


os.chdir("/workspaces/newcpu/market-causality-lab")
sys.path.insert(0, ".")
import main as m  # noqa: E402



def _frame_with_years(years: int) -> pd.DataFrame:
    periods = max(2, int(years * 365.25))
    times = pd.date_range(end="2025-12-31", periods=periods, freq="D")
    return pd.DataFrame({"time": times, "close": 1.0})



def test_timeframe_fallback_chain_for_1m():
    chain = m._timeframe_fallback_chain("1m")
    assert chain[0] == "1m"
    assert chain[-1] == "1d"
    assert chain == ["1m", "5m", "30m", "1h", "4h", "1d"]



def test_load_historical_with_fallback_selects_deeper_timeframe(monkeypatch):
    depth_by_tf = {
        "1m": 2,
        "5m": 3,
        "30m": 5,
        "1h": 26,
        "4h": 26,
        "1d": 26,
    }

    def fake_resolve(timeframe: str, symbol: str = "XAUUSD", data_dir: str = "data") -> Path:
        return Path(data_dir) / f"{timeframe}.csv"

    def fake_load_data(path: str):
        tf = Path(path).stem
        return _frame_with_years(depth_by_tf[tf])

    monkeypatch.setattr(m, "_resolve_timeframe_file", fake_resolve)
    monkeypatch.setattr(m, "load_data", fake_load_data)

    df, dataset_path, applied_tf, meta = m._load_historical_with_fallback(
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=25,
        data_dir="data",
    )

    assert applied_tf == "1h"
    assert dataset_path.name == "1h.csv"
    assert meta["fallback_applied"] is True
    assert meta["fallback_reason"] == "requested_timeframe_depth_below_target"
    assert len(df) > 0



def test_load_historical_with_fallback_uses_best_available_when_no_full_match(monkeypatch):
    depth_by_tf = {
        "1m": 2,
        "5m": 3,
        "30m": 5,
        "1h": 21,
        "4h": 19,
        "1d": 24,
    }

    def fake_resolve(timeframe: str, symbol: str = "XAUUSD", data_dir: str = "data") -> Path:
        return Path(data_dir) / f"{timeframe}.csv"

    def fake_load_data(path: str):
        tf = Path(path).stem
        return _frame_with_years(depth_by_tf[tf])

    monkeypatch.setattr(m, "_resolve_timeframe_file", fake_resolve)
    monkeypatch.setattr(m, "load_data", fake_load_data)

    _df, dataset_path, applied_tf, meta = m._load_historical_with_fallback(
        symbol="XAUUSD",
        timeframe="1m",
        lookback_years=40,
        data_dir="data",
    )

    assert applied_tf == "1d"
    assert dataset_path.name == "1d.csv"
    assert meta["fallback_applied"] is True
    assert meta["fallback_reason"] == "requested_timeframe_depth_below_target_no_full_match"


# ---- MT5 fetch Databento fallback contracts -----------------------------------

def test_mt5_fetch_raises_when_mt5_none_and_no_api_key(monkeypatch):
    """_fetch_via_databento must raise RuntimeError when DATABENTO_API_KEY is absent."""
    import importlib
    import sys

    # Reload mt5_fetch isolated from test env.
    mt5_fetch_path = "/workspaces/newcpu/market-causality-lab/backend/live/mt5_fetch.py"
    spec = importlib.util.spec_from_file_location("_test_mt5_fetch_isolated", mt5_fetch_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)

    import pytest
    with pytest.raises(RuntimeError, match="DATABENTO_API_KEY"):
        mod._fetch_via_databento(count=5)


def test_mt5_fetch_databento_path_normalises_columns(monkeypatch):
    """_fetch_via_databento must return a DataFrame with required OHLCV + time cols."""
    import importlib

    mt5_fetch_path = "/workspaces/newcpu/market-causality-lab/backend/live/mt5_fetch.py"
    spec = importlib.util.spec_from_file_location("_test_mt5_fetch_isolated2", mt5_fetch_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    monkeypatch.setenv("DATABENTO_API_KEY", "test-key")

    # Stub databento.Historical.timeseries.get_range to return a fake DataFrame.
    fake_df = pd.DataFrame({
        "ts_event": pd.to_datetime(["2026-04-03 12:00:00"], utc=True),
        "open": [3100.0],
        "high": [3110.0],
        "low": [3090.0],
        "close": [3105.0],
        "size": [1200],
    })

    class _FakeData:
        def to_df(self):
            return fake_df

    class _FakeTimeseries:
        def get_range(self, **_):
            return _FakeData()

    class _FakeClient:
        timeseries = _FakeTimeseries()

    class _FakeDb:
        Historical = lambda self, key: _FakeClient()  # noqa: E731

    import types
    fake_db_mod = types.ModuleType("databento")
    fake_db_mod.Historical = lambda key: _FakeClient()
    monkeypatch.setitem(sys.modules, "databento", fake_db_mod)

    result = mod._fetch_via_databento(count=5)

    assert "time" in result.columns
    assert "open" in result.columns
    assert "close" in result.columns
    assert "volume" in result.columns
    assert len(result) == 1
