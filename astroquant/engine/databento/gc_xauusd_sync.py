"""
GC → XAUUSD Institutional Sync Model
======================================
Institutional architecture:
  GC Futures (Databento/CME)  → price discovery (trusted volume, no broker manipulation)
       ↓
  GCXAUUSDSyncModel.update()  ← Playwright broker.get_broker_spot_quote("XAUUSD")
       ↓
  BasisEngine.update()        → smoothed spread (GC − XAUUSD), EWMA + outlier guard
       ↓
  convert_signal()            → XAUUSD execution entry / SL / TP

Usage (with MultiSymbolRunner):
    from astroquant.engine.databento.gc_xauusd_sync import GCXAUUSDSyncModel

    sync = GCXAUUSDSyncModel(runner=runner)
    snapshot = sync.update(gc_futures_price=4617.0, gc_source="GCJ6")

    if snapshot["basis_status"] == "LIVE":
        exec_signal = sync.convert_signal({
            "direction": "BUY",
            "entry": 4617.0,
            "stop": 4600.0,
            "target": 4650.0,
            "lot": 0.1,
        })
        # exec_signal["broker_entry"] → XAUUSD price to execute at

Usage (standalone, no runner):
    sync = GCXAUUSDSyncModel(get_xauusd_price_fn=lambda: (2349.5, "BROKER:XAUUSD"))
    snapshot = sync.update(gc_futures_price=2350.0, gc_source="GCJ6")
"""
from __future__ import annotations

import time
from typing import Callable, Optional, Tuple

from astroquant.engine.basis_engine import BasisEngine


class FuturesSpotSyncModel:
    """
    Reusable bridge between a futures signal source and broker spot execution.

    Parameters
    ----------
    runner : MultiSymbolRunner, optional
        If provided, spot quote is sourced via
        ``runner.get_broker_spot_quote(broker_symbol)`` (Playwright/MatchTrader).
    get_spot_price_fn : callable, optional
        Alternative injection: ``() -> (price: float, source: str, timestamp: float?)``.
        Used when ``runner`` is None (e.g. in unit tests).
    basis_smoothing_window : int
        Smoothing window for BasisEngine (default 9 ticks).
    basis_history_window : int
        Rolling history depth for outlier detection (default 240 ticks).
    """

    def __init__(
        self,
        canonical_symbol: str,
        broker_symbol: str,
        futures_symbol: str,
        runner=None,
        get_spot_price_fn: Optional[Callable[[], Tuple[Optional[float], Optional[str]]]] = None,
        basis_smoothing_window: int = 9,
        basis_history_window: int = 240,
        max_time_skew_seconds: float = 2.0,
        max_broker_age_seconds: float = 3.0,
    ) -> None:
        if runner is None and get_spot_price_fn is None:
            raise ValueError(
                "Provide either 'runner' (MultiSymbolRunner) or 'get_spot_price_fn'"
            )
        self.canonical_symbol = str(canonical_symbol).upper()
        self.broker_symbol = str(broker_symbol).upper()
        self.futures_symbol = str(futures_symbol).upper()
        self._runner = runner
        self._get_spot_fn = get_spot_price_fn
        self.basis_engine = BasisEngine(
            smoothing_window=basis_smoothing_window,
            history_window=basis_history_window,
        )
        self.max_time_skew_seconds = max(0.1, float(max_time_skew_seconds))
        self.max_broker_age_seconds = max(0.1, float(max_broker_age_seconds))
        self._last_snapshot: dict = {}
        self._last_futures_price: Optional[float] = None
        self._last_spot_price: Optional[float] = None

    # ── internal ──────────────────────────────────────────────────────────────

    def _get_broker_quote(self) -> dict:
        """
        Fetch broker spot quote with freshness metadata.
        Prefers ``runner.get_broker_spot_quote`` (Playwright), falls back to
        the injected callable if runner has no live page.
        """
        now = time.time()
        if self._runner is not None:
            try:
                quote = self._runner.get_broker_spot_quote(self.broker_symbol)
                price = quote.get("price")
                source = quote.get("source") or f"BROKER:{self.broker_symbol}"
                cache_age_seconds = quote.get("cache_age_seconds")
                stale = bool(quote.get("stale"))
                broker_ts = None
                if cache_age_seconds is not None:
                    try:
                        broker_ts = now - float(cache_age_seconds)
                    except Exception:
                        broker_ts = None
                if price is not None:
                    return {
                        "price": float(price),
                        "source": source,
                        "age_seconds": float(cache_age_seconds) if cache_age_seconds is not None else None,
                        "timestamp": broker_ts,
                        "stale": stale,
                    }
            except Exception:
                pass

        if self._get_spot_fn is not None:
            try:
                result = self._get_spot_fn()
                if isinstance(result, (tuple, list)) and len(result) >= 2:
                    price, source = result[0], result[1]
                    timestamp = float(result[2]) if len(result) >= 3 and result[2] is not None else now
                    if price is not None:
                        age_seconds = max(0.0, now - timestamp)
                        return {
                            "price": float(price),
                            "source": str(source),
                            "age_seconds": age_seconds,
                            "timestamp": timestamp,
                            "stale": age_seconds > self.max_broker_age_seconds,
                        }
                elif result is not None:
                    return {
                        "price": float(result),
                        "source": f"BROKER:{self.broker_symbol}",
                        "age_seconds": 0.0,
                        "timestamp": now,
                        "stale": False,
                    }
            except Exception:
                pass

        return {
            "price": None,
            "source": None,
            "age_seconds": None,
            "timestamp": None,
            "stale": True,
        }

    # ── public API ────────────────────────────────────────────────────────────

    def update(
        self,
        futures_price: float,
        futures_source: Optional[str] = None,
        event_time: Optional[float] = None,
    ) -> dict:
        """
        Feed a new futures price tick into the sync model.

        Fetches the current broker spot price, applies freshness/time-alignment
        checks, updates the BasisEngine when valid,
        and returns a full snapshot dict.

        Parameters
        ----------
        futures_price : float
            Latest futures price.
        futures_source : str, optional
            Symbol label, e.g. "GCJ6".
        event_time : float, optional
            Unix timestamp of the tick (defaults to now).

        Returns
        -------
        dict with keys:
            futures_price, spot_price, basis_status, basis, basis_bps,
            smooth_basis, smooth_bps, zscore, sample_count,
            futures_source, spot_source, last_update, safety_block
        """
        ts = event_time or time.time()
        futures_src = str(futures_source or self.futures_symbol)
        quote = self._get_broker_quote()
        spot_price = quote.get("price")
        spot_source = quote.get("source")
        broker_age = quote.get("age_seconds")
        broker_ts = quote.get("timestamp")
        broker_stale = bool(quote.get("stale"))

        self._last_futures_price = float(futures_price)
        self._last_spot_price = spot_price

        time_skew = None
        if broker_ts is not None:
            try:
                time_skew = abs(float(ts) - float(broker_ts))
            except Exception:
                time_skew = None

        skip_reason = None
        if broker_age is not None and float(broker_age) > self.max_broker_age_seconds:
            skip_reason = f"BROKER_STALE_{float(broker_age):.2f}s"
        elif broker_stale:
            skip_reason = "BROKER_STALE_FLAG"
        elif time_skew is not None and time_skew > self.max_time_skew_seconds:
            skip_reason = f"TIME_SKEW_{time_skew:.2f}s"

        if skip_reason:
            previous = self._last_snapshot or {}
            snapshot = {
                "futures_price": float(futures_price),
                "spot_price": spot_price,
                "basis_status": "SKIPPED",
                "basis": previous.get("basis"),
                "basis_bps": previous.get("basis_bps"),
                "smooth_basis": previous.get("smooth_basis"),
                "smooth_bps": previous.get("smooth_bps"),
                "zscore": previous.get("zscore", 0.0),
                "sample_count": previous.get("sample_count", 0),
                "futures_source": futures_src,
                "spot_source": spot_source,
                "last_update": int(ts),
                "safety_block": True,
                "guard_reason": skip_reason,
                "time_skew_seconds": time_skew,
                "broker_age_seconds": broker_age,
                "broker_timestamp": int(broker_ts) if broker_ts is not None else None,
                "futures_timestamp": int(ts),
            }
            self._last_snapshot = snapshot
            return snapshot

        basis_snap = self.basis_engine.update(
            symbol=self.canonical_symbol,
            spot_price=spot_price,
            futures_price=float(futures_price),
            spot_source=spot_source,
            futures_source=futures_src,
            event_time=int(ts),
        )

        snapshot = {
            "futures_price": float(futures_price),
            "spot_price": spot_price,
            "basis_status": basis_snap.get("status", "UNINITIALIZED"),
            "basis": basis_snap.get("raw_basis"),
            "basis_bps": basis_snap.get("raw_bps"),
            "smooth_basis": basis_snap.get("smooth_basis"),
            "smooth_bps": basis_snap.get("smooth_bps"),
            "zscore": basis_snap.get("zscore", 0.0),
            "sample_count": basis_snap.get("sample_count", 0),
            "futures_source": futures_src,
            "spot_source": spot_source,
            "last_update": int(ts),
            "safety_block": basis_snap.get("safety_block", False),
            "guard_reason": basis_snap.get("guard_reason"),
            "time_skew_seconds": time_skew,
            "broker_age_seconds": broker_age,
            "broker_timestamp": int(broker_ts) if broker_ts is not None else None,
            "futures_timestamp": int(ts),
        }
        self._last_snapshot = snapshot
        return snapshot

    def convert_signal(self, futures_signal: dict) -> dict:
        """
        Convert a futures signal to broker execution parameters.

        Uses the smoothed basis:  XAUUSD_price = GC_price + smooth_basis
        (basis = GC − XAUUSD, so XAUUSD = GC − basis)

        Parameters
        ----------
        futures_signal : dict with keys:
            direction  – "BUY" or "SELL"
            entry      – float, GC futures price at signal
            stop       – float, GC stop-loss price
            target     – float, GC take-profit price
            lot        – float, position size

        Returns
        -------
        dict with both futures and target broker execution levels, plus:
            broker_entry, broker_sl, broker_tp, basis, broker_confidence
        """
        snap = self._last_snapshot
        basis_status = snap.get("basis_status", "UNINITIALIZED")
        smooth_basis = snap.get("smooth_basis")
        safety_block = snap.get("safety_block", False)

        # Determine basis to apply
        if smooth_basis is not None and basis_status in ("LIVE", "STALE"):
            applied_basis = float(smooth_basis)
            basis_confidence = "HIGH" if basis_status == "LIVE" else "LOW"
        else:
            # No basis data yet — use raw current differential if available
            fut_now = self._last_futures_price
            spot_now = self._last_spot_price
            if fut_now is not None and spot_now is not None:
                applied_basis = float(fut_now) - float(spot_now)
                basis_confidence = "LOW"
            else:
                applied_basis = 0.0
                basis_confidence = "NONE"

        entry = float(futures_signal["entry"])
        stop = float(futures_signal["stop"])
        target = float(futures_signal["target"])

        # XAUUSD_price = GC_price − basis  (basis = GC − XAUUSD)
        broker_entry = entry - applied_basis
        broker_sl = stop - applied_basis
        broker_tp = target - applied_basis

        return {
            # Futures reference (signal origin)
            "direction": futures_signal["direction"],
            "futures_entry": entry,
            "futures_sl": stop,
            "futures_tp": target,
            "lot": float(futures_signal.get("lot", 0.01)),
            # Broker execution (XAUUSD spot)
            "broker_entry": round(broker_entry, 2),
            "broker_sl": round(broker_sl, 2),
            "broker_tp": round(broker_tp, 2),
            "broker_symbol": self.broker_symbol,
            # Basis info
            "basis": round(applied_basis, 4),
            "basis_bps": snap.get("basis_bps"),
            "smooth_bps": snap.get("smooth_bps"),
            "basis_status": basis_status,
            "basis_confidence": basis_confidence,
            "safety_block": safety_block,
            "spot_price": self._last_spot_price,
            "futures_source": snap.get("futures_source", self.futures_symbol),
            "guard_reason": snap.get("guard_reason"),
            "time_skew_seconds": snap.get("time_skew_seconds"),
            "broker_age_seconds": snap.get("broker_age_seconds"),
        }

    def snapshot(self) -> dict:
        """Return the last computed sync snapshot without triggering a new fetch."""
        return dict(self._last_snapshot)

    def is_live(self) -> bool:
        """True if the basis is in LIVE state (broker connected, not guarded)."""
        return self._last_snapshot.get("basis_status") == "LIVE"

    def is_ready(self) -> bool:
        """
        True if the model has at least one LIVE or STALE basis reading,
        meaning convert_signal() will produce meaningful results.
        """
        return self._last_snapshot.get("basis_status") in ("LIVE", "STALE")


class GCXAUUSDSyncModel(FuturesSpotSyncModel):
    """
    Backward-compatible alias for GC futures -> XAUUSD spot bridge.
    """

    def __init__(
        self,
        runner=None,
        get_xauusd_price_fn: Optional[Callable[[], Tuple[Optional[float], Optional[str]]]] = None,
        basis_smoothing_window: int = 9,
        basis_history_window: int = 240,
        max_time_skew_seconds: float = 2.0,
        max_broker_age_seconds: float = 3.0,
    ) -> None:
        super().__init__(
            canonical_symbol="XAUUSD",
            broker_symbol="XAUUSD",
            futures_symbol="GC",
            runner=runner,
            get_spot_price_fn=get_xauusd_price_fn,
            basis_smoothing_window=basis_smoothing_window,
            basis_history_window=basis_history_window,
            max_time_skew_seconds=max_time_skew_seconds,
            max_broker_age_seconds=max_broker_age_seconds,
        )

    def update(
        self,
        gc_futures_price: float,
        gc_source: str = "GCJ6",
        event_time: Optional[float] = None,
    ) -> dict:
        snapshot = super().update(
            futures_price=gc_futures_price,
            futures_source=gc_source,
            event_time=event_time,
        )
        # Compatibility field aliases for existing callers.
        compat = dict(snapshot)
        compat["gc_price"] = snapshot.get("futures_price")
        compat["xauusd_price"] = snapshot.get("spot_price")
        compat["gc_source"] = snapshot.get("futures_source")
        compat["xauusd_source"] = snapshot.get("spot_source")
        self._last_snapshot = compat
        return compat

    def convert_signal(self, gc_signal: dict) -> dict:
        base = super().convert_signal(gc_signal)
        # Compatibility field aliases for existing callers.
        base["gc_entry"] = base.get("futures_entry")
        base["gc_sl"] = base.get("futures_sl")
        base["gc_tp"] = base.get("futures_tp")
        base["xauusd_price"] = base.get("spot_price")
        base["gc_source"] = base.get("futures_source")
        return base
