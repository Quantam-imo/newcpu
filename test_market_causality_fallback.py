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
