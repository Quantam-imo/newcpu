import os
import databento as db
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from astroquant.engine.databento.final_engine import AstroQuantFinalDataEngine

def fetch_databento_data(symbols: List[str], schema: str, start: str, end: str, dataset: Optional[str] = None, api_key: Optional[str] = None, limit: Optional[int] = None, stype_in: Optional[str] = None):
    """
    Fetch data from Databento for given symbols, schema, and time window.
    Returns a pandas DataFrame or raises Exception.
    """
    if api_key is None:
        api_key = os.environ.get("DATABENTO_API_KEY")
    if dataset is None:
        dataset = os.environ.get("DATABENTO_DATASET", "GLBX.MDP3")
    client = db.Historical(api_key)
    kwargs = dict(
        dataset=dataset,
        schema=schema,
        symbols=symbols,
        start=start,
        end=end,
        limit=limit,
    )
    if stype_in:
        kwargs["stype_in"] = stype_in
    # Add timeout to Databento call (5 seconds)
    try:
        result = client.timeseries.get_range(**kwargs, timeout=5)
    except TypeError:
        # If Databento SDK does not support timeout param, fallback to default
        result = client.timeseries.get_range(**kwargs)
    return result.to_df()


_FINAL_ENGINE = None


def _get_final_engine() -> AstroQuantFinalDataEngine:
    global _FINAL_ENGINE
    if _FINAL_ENGINE is None:
        _FINAL_ENGINE = AstroQuantFinalDataEngine()
    return _FINAL_ENGINE


ROOT_MONTH_CYCLES: Dict[str, List[str]] = {
    "GC": ["G", "J", "M", "Q", "V", "Z"],
    "NQ": ["H", "M", "U", "Z"],
    "6E": ["H", "M", "U", "Z"],
    "YM": ["H", "M", "U", "Z"],
}

MONTH_CODE_TO_MONTH: Dict[str, int] = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


def _dynamic_contract_candidates(root: str, max_count: int = 3) -> List[str]:
    root_key = str(root or "").upper()
    cycles = ROOT_MONTH_CYCLES.get(root_key, [])
    if not cycles:
        return []

    month_sequence = []
    for code in cycles:
        month_num = MONTH_CODE_TO_MONTH.get(code)
        if month_num is not None:
            month_sequence.append((month_num, code))
    month_sequence.sort(key=lambda x: x[0])
    if not month_sequence:
        return []

    now = datetime.now(timezone.utc)
    current_month = int(now.month)
    year = int(now.year)
    # Commodity futures (GC, CL, SI, HG, NG) expire BEFORE the delivery month.
    # By day 5 of month N, contract N is already expired — advance to next cycle.
    COMMODITY_ROOTS = {"GC", "CL", "SI", "HG", "NG", "ZC", "ZW", "ZS"}
    if root_key in COMMODITY_ROOTS and now.day >= 5:
        month_cursor = current_month + 1
        if month_cursor > 12:
            month_cursor = 1
            year += 1
    else:
        month_cursor = current_month
    max_needed = max(1, int(max_count))

    picks: List[str] = []
    attempts = 0
    while len(picks) < max_needed and attempts < 16:
        attempts += 1
        next_pair = None
        for month_num, code in month_sequence:
            if month_num >= month_cursor:
                next_pair = (month_num, code)
                break
        if next_pair is None:
            year += 1
            month_cursor = 1
            continue

        month_num, code = next_pair
        contract = f"{root_key}{code}{str(year)[-1]}"
        if contract not in picks:
            picks.append(contract)
        month_cursor = month_num + 1
        if month_cursor > 12:
            year += 1
            month_cursor = 1

    return picks


def resolve_symbol_candidates(symbol: str) -> List[str]:
    """
    Resolve user-facing symbols into concrete contract candidates for the
    production final data engine.
    """
    key = str(symbol or "").strip().upper()

    root_alias: Dict[str, str] = {
        "XAUUSD": "GC",
        "GC": "GC",
        "GC.FUT": "GC",
        "GC-F": "GC",
        "GC.C.1": "GC",
        "NQ": "NQ",
        "NQ.FUT": "NQ",
        "NQ.C.1": "NQ",
        "EURUSD": "6E",
        "6E": "6E",
        "6E.FUT": "6E",
        "6E.C.1": "6E",
        "US30": "YM",
        "YM": "YM",
        "YM.FUT": "YM",
        "YM.C.1": "YM",
    }

    if key in root_alias:
        root = root_alias[key]
        candidates: List[str] = [f"{root}.c.1"]
        dynamic = _dynamic_contract_candidates(root, max_count=3)
        if dynamic:
            candidates.extend(dynamic)
        # Keep order but remove duplicates.
        deduped: List[str] = []
        seen = set()
        for item in candidates:
            token = str(item or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        if deduped:
            return deduped

    # Generic compatibility for canonical feed-style aliases like 6E.FUT/YM.FUT.
    if key.endswith(".FUT"):
        root = key.split(".", 1)[0].upper()
        root = root_alias.get(root, root)
        candidates: List[str] = [f"{root}.c.1"]
        dynamic = _dynamic_contract_candidates(root, max_count=3)
        if dynamic:
            candidates.extend(dynamic)
        deduped: List[str] = []
        seen = set()
        for item in candidates:
            token = str(item or "").strip()
            if not token or token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        if deduped:
            return deduped

    # If a concrete root-month symbol is already provided, use as-is.
    if len(key) >= 4 and key[-1].isdigit():
        return [key]

    return [key]


def dataframe_to_candles(df: pd.DataFrame, limit: int = 80, bucket_minutes: int = 1) -> List[dict]:
    """
    Convert either OHLCV or trades dataframe into a candle list expected by frontend.
    """
    if df is None or len(df) == 0:
        return []

    frame = df.copy()
    if "ts_event" in frame.columns:
        frame = frame.set_index("ts_event")
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index, utc=True, errors="coerce")
    frame = frame[~frame.index.isna()]
    if len(frame) == 0:
        return []

    if {"open", "high", "low", "close"}.issubset(set(frame.columns)):
        out = frame.copy()
        if "volume" not in out.columns:
            out["volume"] = 0.0
        out = out[["open", "high", "low", "close", "volume"]]
    elif "price" in frame.columns:
        price = pd.to_numeric(frame["price"], errors="coerce")
        bucket = f"{max(1, int(bucket_minutes))}min"
        ohlc = price.resample(bucket).ohlc()
        if "size" in frame.columns:
            vol = pd.to_numeric(frame["size"], errors="coerce").resample(bucket).sum()
        else:
            vol = price.resample(bucket).count().astype(float)
        out = ohlc.join(vol.rename("volume")).dropna(subset=["open", "high", "low", "close"])
    else:
        return []

    rows = out.tail(max(1, int(limit)))
    candles: List[dict] = []
    for ts, row in rows.iterrows():
        iso = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
        candles.append(
            {
                "timestamp": iso,
                "time": iso,
                "open": float(row.get("open", 0.0) or 0.0),
                "high": float(row.get("high", 0.0) or 0.0),
                "low": float(row.get("low", 0.0) or 0.0),
                "close": float(row.get("close", 0.0) or 0.0),
                "volume": float(row.get("volume", 0.0) or 0.0),
            }
        )
    return candles


def fetch_candles_unified(symbol: str, limit: int = 80, minutes: Optional[int] = None) -> Tuple[List[dict], dict]:
    """
    Unified historical fetch path using AstroQuantFinalDataEngine.

    Returns: (candles, meta)
    """
    candidate_symbols = resolve_symbol_candidates(symbol)
    lookback = int(minutes if minutes is not None else limit)
    lookback = max(1, lookback)

    engine = _get_final_engine()
    result = engine.fetch_with_fallback(candidate_symbols, minutes=lookback)
    candles = dataframe_to_candles(result.dataframe, limit=limit, bucket_minutes=1)

    meta = {
        "resolved_symbol": result.symbol,
        "records": result.records,
        "fallback_used": bool(result.fallback_used),
        "reason": result.reason,
        "window_start": result.start.isoformat(),
        "window_end": result.end.isoformat(),
    }
    return candles, meta