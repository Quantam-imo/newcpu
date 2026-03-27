"""
Multi-Timeframe Confirmation Filter
====================================
Requires 4h trend = UP before accepting 1h BUY signals.
Reduces regime-clustering drawdown by filtering contra-trend entries.

Method:
  1. Load 4h OHLC data at initialization
  2. For each 1h signal timestamp, find the most recent 4h candle
  3. Compute 4h 10-bar trend (same as 1h)
  4. Reject 1h BUY if 4h trend != UP
  5. Accept all SELL signals (assume we manage shorts separately)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pandas as pd


class MultiFrameFilter:
    """Load 4h data once and reuse for all filter checks."""

    def __init__(self, data_path: Optional[str] = None):
        """
        Args:
            data_path: Path to 4h OHLC CSV (default: data/XAU_4h_data.csv relative to project root)
        """
        if data_path is None:
            project_root = Path(__file__).parent.parent.parent
            data_path = project_root / "data" / "XAU_4h_data.csv"

        # Try both semicolon and comma delimiters
        try:
            self.df_4h = pd.read_csv(data_path, sep=";")
        except:
            self.df_4h = pd.read_csv(data_path, sep=",")

        # Handle column names: could be 'time', 'Time', 'Date', etc.
        time_col = None
        for col in self.df_4h.columns:
            if col.lower() in ["time", "date", "timestamp"]:
                time_col = col
                break

        if time_col is None:
            raise ValueError(f"4h data must have a time column. Found columns: {list(self.df_4h.columns)}")

        # Rename to standard 'time'
        self.df_4h = self.df_4h.rename(columns={time_col: "time"})

        self.df_4h["time"] = pd.to_datetime(self.df_4h["time"])
        self.df_4h = self.df_4h.sort_values("time").reset_index(drop=True)
        self._trend_cache = {}  # {timestamp_str: trend} to avoid re-computing

    def get_4h_trend(self, timestamp: pd.Timestamp) -> str:
        """
        Get 4h trend on or before the given 1h timestamp.

        Returns: "UP", "DOWN", or "NONE" (if insufficient historical bars)
        """
        ts_str = str(timestamp)
        if ts_str in self._trend_cache:
            return self._trend_cache[ts_str]

        # Find the most recent 4h bar at or before this timestamp
        relevant = self.df_4h[self.df_4h["time"] <= timestamp]
        if len(relevant) < 10:
            trend = "NONE"
        else:
            # Handle both 'close' and 'Close' column names
            close_col = "close" if "close" in relevant.columns else "Close"
            closes = relevant[close_col].iloc[-10:].values
            if len(closes) == 10:
                trend = "UP" if closes[-1] > closes[0] else "DOWN"
            else:
                trend = "NONE"

        self._trend_cache[ts_str] = trend
        return trend


def multiframe_filter(signal: str, timestamp: pd.Timestamp, mf: MultiFrameFilter) -> str:
    """
    Apply multi-timeframe confirmation:
      - BUY: only if 4h trend is UP
      - SELL: always pass (assume we don't short, or manage via separate logic)
      - WAIT/other: pass through

    Args:
        signal: "BUY", "SELL", "WAIT"
        timestamp: the bar's timestamp (from memory record) or None
        mf: initialized MultiFrameFilter instance

    Returns:
        "BUY", "SELL", or "WAIT"
    """
    if timestamp is None:
        # Can't check 4h trend without timestamp, so pass signal through
        return signal

    if signal == "BUY":
        trend_4h = mf.get_4h_trend(timestamp)
        if trend_4h != "UP":
            return "WAIT"
        return "BUY"
    elif signal == "SELL":
        # For now, accept all SELL (could add 4h DOWN requirement if shorting)
        return "SELL"
    else:
        return signal
