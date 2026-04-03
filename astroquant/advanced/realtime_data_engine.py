"""
AstroQuant Advanced Real-Time Data Engine
=========================================

Purpose:
- Pull live/recent candles from Databento through MarketFeed
- Run Gann + ICT + Astro confluence on each update
- Emit execution-ready signal payloads for downstream routing/execution

This module is additive and does not alter existing backend routers.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

import pandas as pd

from astroquant.engine.market_feed import MarketFeed
from astroquant.engine.gann.gann_master_engine import GannMasterEngine
from astroquant.advanced.ict_structure_engine import ICTStructureEngine
from astroquant.advanced.astro_engine import astro_score
from astroquant.execution.signal_engine import generate_signal
from astroquant.core.time_engine import time_from_extreme, detect_time_cycle
from astroquant.core.price_engine import price_range
from astroquant.advanced.projection_engine import project_levels
from astroquant.advanced.harmonic_engine import sqrt2_levels
from astroquant.advanced.cluster_engine import detect_clusters


@dataclass
class FeedConfig:
    dataset: str = "GLBX.MDP3"
    symbol: str = "GC.c.0"
    lookback_minutes: int = 240
    poll_seconds: int = 15


class RealTimeDataEngine:
    """
    Real-time orchestrator for the modular starter pack.

    Usage:
        engine = RealTimeDataEngine()
        snap = engine.compute_snapshot()
        print(snap["signal"])

        # continuous mode
        engine.run_forever(on_signal=lambda s: print(s))
    """

    def __init__(self, api_key: Optional[str] = None, feed_config: Optional[FeedConfig] = None):
        key = str(api_key or os.getenv("DATABENTO_API_KEY", "")).strip()
        self.feed = MarketFeed(key)
        self.cfg = feed_config or FeedConfig()
        # Keep runtime settings inside safe operational bounds.
        self.cfg.lookback_minutes = max(1, min(int(self.cfg.lookback_minutes), 7 * 24 * 60))
        self.cfg.poll_seconds = max(1, min(int(self.cfg.poll_seconds), 3600))
        self.gann = GannMasterEngine()
        self.ict = ICTStructureEngine()

    def _candles_to_df(self, candles: list[dict]) -> pd.DataFrame:
        if not candles:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(candles)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "time" in df.columns:
            df["time"] = pd.to_numeric(df["time"], errors="coerce")
            df["datetime"] = pd.to_datetime(df["time"], unit="s", utc=True, errors="coerce")
            df = df.dropna(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        return df

    def fetch_recent_candles(self) -> pd.DataFrame:
        """Fetch latest OHLCV candles from Databento via MarketFeed."""
        candles = self.feed.get_ohlcv(
            dataset=self.cfg.dataset,
            symbol=self.cfg.symbol,
            lookback_minutes=self.cfg.lookback_minutes,
        )
        return self._candles_to_df(candles)

    def _astro_from_last_bar(self, df: pd.DataFrame) -> dict:
        if df.empty:
            return {"score": 0, "bias": "NEUTRAL", "aspects": 0, "retrogrades": [], "trigger": {}}
        try:
            ts = pd.to_datetime(df["datetime"].iloc[-1], utc=True)
            import swisseph as swe
            jd = swe.julday(ts.year, ts.month, ts.day, ts.hour + ts.minute / 60.0 + ts.second / 3600.0)
            return astro_score(jd)
        except Exception:
            return astro_score(None)

    def compute_snapshot(self) -> dict:
        """
        Compute one live confluence snapshot from latest candles.

        Returns:
        {
          status, signal, confidence, timestamp_utc,
          components: {gann, ict, astro, time_cycles, cluster},
          diagnostics: {rows, feed_health, last_error}
        }
        """
        try:
            df = self.fetch_recent_candles()
        except Exception as exc:
            self.feed.last_error = str(exc)
            return {
                "status": "UNAVAILABLE",
                "signal": "NO TRADE",
                "confidence": 0.0,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "components": {},
                "diagnostics": {
                    "rows": 0,
                    "feed_health": self.feed.health(),
                    "last_error": self.feed.last_error,
                    "reason": "FEED_FETCH_FAILED",
                },
            }

        if len(df) < 60:
            return {
                "status": "UNAVAILABLE",
                "signal": "NO TRADE",
                "confidence": 0.0,
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "components": {},
                "diagnostics": {
                    "rows": int(len(df)),
                    "feed_health": self.feed.health(),
                    "last_error": self.feed.last_error,
                    "reason": "INSUFFICIENT_CANDLES",
                },
            }

        # Gann analysis window
        window = df.tail(120)
        candles = [
            {
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume or 0.0),
            }
            for r in window.itertuples(index=False)
        ]
        gann_result = self.gann.analyze(candles)
        gann_score = float(gann_result.get("score", 0.0) or 0.0)

        # ICT analysis
        ict_result = self.ict.analyze(df.tail(60), df.tail(180))
        ict_score = int(ict_result.get("ict_score", 0) or 0)

        # Astro analysis
        astro = self._astro_from_last_bar(df)
        astro_sc = int(astro.get("score", 0) or 0)

        # Time cycle + clusters
        current_index = len(df) - 1
        swing_index = max(0, current_index - 90)
        time_count = time_from_extreme(current_index, swing_index)
        time_cycles = detect_time_cycle(time_count)

        last = df.iloc[-1]
        delta = price_range(float(last["high"]), float(last["low"]))
        levels = project_levels(float(last["close"]), delta)
        harmonics = sqrt2_levels(float(last["close"]))
        clusters = detect_clusters(levels + harmonics)

        signal = generate_signal(
            time_align=1 if time_cycles else 0,
            price_hit=1 if gann_score > 0 else 0,
            geometry_ok=1 if ict_score > 0 else 0,
            structure_ok=1 if astro_sc > 0 else 0,
            cluster_ok=1 if clusters else 0,
        )

        confidence = (
            int(bool(time_cycles))
            + int(gann_score > 0)
            + int(ict_score > 0)
            + int(astro_sc > 0)
            + int(bool(clusters))
        ) / 5.0

        return {
            "status": "OK",
            "signal": signal,
            "confidence": round(confidence, 4),
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "components": {
                "gann": {"score": gann_score, "signal": gann_result.get("direction")},
                "ict": {"score": ict_score, "direction": ict_result.get("direction")},
                "astro": {"score": astro_sc, "bias": astro.get("bias")},
                "time_cycles": list(time_cycles),
                "cluster": {"count": len(clusters)},
            },
            "diagnostics": {
                "rows": int(len(df)),
                "dataset": self.cfg.dataset,
                "symbol": self.cfg.symbol,
                "feed_health": self.feed.health(),
                "last_error": self.feed.last_error,
            },
        }

    def run_forever(self, on_signal: Optional[Callable[[dict], None]] = None, max_iterations: Optional[int] = None) -> None:
        """Poll the feed and emit snapshots continuously."""
        iterations = 0
        while True:
            snapshot = self.compute_snapshot()
            if on_signal is not None:
                try:
                    on_signal(snapshot)
                except Exception:
                    # Keep the polling loop alive even if a callback fails.
                    pass
            iterations += 1
            if max_iterations is not None and iterations >= int(max_iterations):
                return
            time.sleep(max(1, min(int(self.cfg.poll_seconds), 3600)))
