from __future__ import annotations

import pandas as pd

try:
    import MetaTrader5 as mt5
except Exception:  # pragma: no cover - depends on local MT5 environment
    mt5 = None


def fetch_xauusd(count: int = 500, timeframe=None) -> pd.DataFrame:
    if mt5 is None:
        raise RuntimeError("MetaTrader5 package is not available in this environment")

    tf = timeframe if timeframe is not None else mt5.TIMEFRAME_M5

    if not mt5.initialize():
        raise RuntimeError("Failed to initialize MetaTrader5 terminal")

    rates = mt5.copy_rates_from_pos("XAUUSD", tf, 0, count)
    if rates is None:
        raise RuntimeError("MetaTrader5 returned no rates for XAUUSD")

    df = pd.DataFrame(rates)
    if df.empty:
        raise RuntimeError("No XAUUSD rows returned from MetaTrader5")

    df["time"] = pd.to_datetime(df["time"], unit="s")

    # Normalize to the internal naming used by the rest of the pipeline.
    if "tick_volume" in df.columns and "volume" not in df.columns:
        df = df.rename(columns={"tick_volume": "volume"})

    return df