from fastapi import APIRouter, Query
from typing import Any
from astroquant.backend.runtime import get_runner, normalize_runtime_symbol
from datetime import datetime, timezone

router = APIRouter()


def _to_epoch_seconds(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = int(value)
        if ts > 10_000_000_000:
            ts = int(ts / 1000)
        return ts if ts > 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        except Exception:
            return None
    return None

# Endpoint: /spread_offset_history
@router.get("/spread_offset_history")
@router.get("/api/spread_offset_history")
def get_spread_offset_history(
    symbol: str = Query("XAUUSD", description="Symbol, e.g. XAUUSD, NQ, EURUSD, BTC, US30"),
    lookback_minutes: int = Query(240, description="Lookback window in minutes (default 240, max 4320)"),
) -> Any:
    canonical_symbol = normalize_runtime_symbol(symbol)
    runner = get_runner()
    market_data = runner.get_market_data(canonical_symbol) or {}
    # Primary: broker tick-derived spot candles.
    spot_candles = list(runner._spot_candles_from_ticks(canonical_symbol, lookback_minutes=lookback_minutes) or [])
    # Secondary: broader spot source (Databento/broker abstraction) for weekend or sparse tick windows.
    spot_source, db_candles = runner.get_spot_candles(canonical_symbol, lookback_minutes=lookback_minutes, record_limit=2400)
    db_candles = list(db_candles or [])

    if not spot_candles and db_candles:
        normalized = []
        for row in db_candles:
            if not isinstance(row, dict):
                continue
            ts = _to_epoch_seconds(row.get("time") or row.get("timestamp"))
            if ts is None:
                continue
            try:
                o = float(row.get("open") or 0)
                h = float(row.get("high") or 0)
                l = float(row.get("low") or 0)
                c = float(row.get("close") or 0)
                v = float(row.get("volume") or 0)
            except Exception:
                continue
            if min(o, h, l, c) <= 0:
                continue
            normalized.append({"time": ts, "open": o, "high": h, "low": l, "close": c, "volume": max(0.0, v)})
        spot_candles = normalized

    used_proxy = False
    if not spot_candles:
        _, fut_candles = runner.get_futures_candles(
            canonical_symbol,
            lookback_minutes=lookback_minutes,
            record_limit=2400,
            prefer_cached=True,
            max_probe_seconds=2.0,
        )
        proxy_rows = []
        for row in list(fut_candles or [])[-400:]:
            if not isinstance(row, dict):
                continue
            ts = _to_epoch_seconds(row.get("time") or row.get("timestamp"))
            if ts is None:
                continue
            try:
                o = float(row.get("open") or 0)
                h = float(row.get("high") or 0)
                l = float(row.get("low") or 0)
                c = float(row.get("close") or 0)
                v = float(row.get("volume") or 0)
            except Exception:
                continue
            if min(o, h, l, c) <= 0:
                continue
            proxy_rows.append({"time": ts, "open": o, "high": h, "low": l, "close": c, "volume": max(0.0, v)})
        if proxy_rows:
            spot_candles = proxy_rows
            used_proxy = True
            if not spot_source:
                spot_source = "FUTURES_PROXY"
    # Get basis (spread/offset) history
    basis_snap = runner.get_basis_snapshot(canonical_symbol)
    offset_guard = runner.offset_guard_snapshot(canonical_symbol, basis_snapshot=basis_snap)
    broker_quote = runner.get_broker_spot_quote(canonical_symbol) or {}
    basis_raw = basis_snap.get("raw_basis") if isinstance(basis_snap, dict) else None
    try:
        basis_raw = float(basis_raw) if basis_raw is not None else None
    except Exception:
        basis_raw = None
    if basis_raw is not None:
        for row in spot_candles:
            if isinstance(row, dict) and "raw_basis" not in row:
                row["raw_basis"] = basis_raw
    return {
        "symbol": canonical_symbol,
        "spot_candles": spot_candles,
        "db_candles": db_candles[-400:],
        "basis": basis_snap,
        "offset_guard": offset_guard,
        "broker_quote": broker_quote.get("snapshot") or {},
        "signal_detection": {
            "count": len(list(market_data.get("absorption_levels") or [])),
            "absorption": bool(market_data.get("absorption_levels")),
        },
        "meta": {
            "lookback_minutes": lookback_minutes,
            "count": len(spot_candles),
            "spot_source": spot_source,
            "used_proxy": used_proxy,
        },
    }
