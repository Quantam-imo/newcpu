"""
AstroQuant Advanced Backtest Runner
=====================================
Wires Gann + ICT + Astro engines together into BacktestEngine for a
single-call multi-engine historical backtest.

Each bar is scored by three engines:
  1. Gann    — uses GannMasterEngine.analyze(window)
  2. ICT     — uses ICTStructureEngine.analyze(df_window, htf_window)
  3. Astro   — uses astro_score(jd) with bar timestamp if available

All three scores feed into generate_signal() for a final STRONG/WEAK/NO TRADE
call.  Results are stored in BacktestEngine under separate signal_source keys
so you can compare engine performance side-by-side.

Usage:
    from astroquant.advanced.backtest_runner import BacktestRunner
    import pandas as pd

    df = pd.read_csv("xauusd_1m.csv")   # must have open,high,low,close columns
    runner = BacktestRunner()
    report = runner.run(df)
    print(report)
"""
from __future__ import annotations

import math
from typing import Optional

import pandas as pd

from astroquant.backtesting.backtest_engine import BacktestEngine, Trade
from astroquant.execution.signal_engine import generate_signal
from astroquant.engine.gann.gann_master_engine import GannMasterEngine
from astroquant.advanced.ict_structure_engine import ICTStructureEngine
from astroquant.advanced.astro_engine import astro_score
from astroquant.core.time_engine import detect_time_cycle, time_from_extreme
from astroquant.core.price_engine import price_range
from astroquant.advanced.cluster_engine import detect_clusters
from astroquant.advanced.projection_engine import project_levels
from astroquant.advanced.harmonic_engine import sqrt2_levels

# Minimum lookback window for each engine
_GANN_WINDOW = 50
_ICT_WINDOW = 20
_HTF_WINDOW = 100


def _candles_from_df(df: pd.DataFrame, start: int, end: int) -> list[dict]:
    """Convert a slice of a DataFrame to a list of OHLCV dicts for GannMasterEngine."""
    return [
        {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0)),
        }
        for _, row in df.iloc[start:end].iterrows()
    ]


def _jd_from_bar(df: pd.DataFrame, idx: int) -> Optional[float]:
    """Extract Julian Day from a bar timestamp (columns preferred, then index)."""
    try:
        import swisseph as swe

        ts = None
        if "datetime" in df.columns:
            ts = pd.to_datetime(df.iloc[idx]["datetime"], errors="coerce", utc=True)
        elif "time" in df.columns:
            raw_t = df.iloc[idx]["time"]
            ts = pd.to_datetime(raw_t, errors="coerce", utc=True)
            if pd.isna(ts):
                ts = pd.to_datetime(raw_t, errors="coerce", unit="s", utc=True)
        if pd.isna(ts) or ts is None:
            ts = pd.to_datetime(df.index[idx], errors="coerce", utc=True)
        if pd.isna(ts):
            return None

        return swe.julday(ts.year, ts.month, ts.day,
                          ts.hour + ts.minute / 60.0 + ts.second / 3600.0)
    except Exception:
        return None


def _resolve_trade_direction(gann_score_raw: float, ict_direction: str, astro_score_raw: int) -> Optional[str]:
    """Resolve trade direction without introducing a default bullish bias."""
    g = float(gann_score_raw or 0.0)
    if g > 0:
        return "BUY"
    if g < 0:
        return "SELL"

    direction = str(ict_direction or "").upper()
    if direction in {"BUY", "SELL"}:
        return direction

    a = int(astro_score_raw or 0)
    if a > 0:
        return "BUY"
    if a < 0:
        return "SELL"
    return None


class BacktestRunner:
    """
    Multi-engine historical backtest.

    Args:
        starting_balance:  Paper trading account balance.
        risk_percent:      Risk per trade as a percentage of balance.
        htf_ratio:         How many LTF bars equal one HTF bar (default 5).
    """

    def __init__(
        self,
        starting_balance: float = 50_000.0,
        risk_percent: float = 1.0,
        htf_ratio: int = 5,
    ):
        self.engine = BacktestEngine(starting_balance=starting_balance, risk_percent=risk_percent)
        self.gann = GannMasterEngine()
        self.ict = ICTStructureEngine()
        self.htf_ratio = htf_ratio

    def run(self, df: pd.DataFrame, htf_df: Optional[pd.DataFrame] = None) -> dict:
        """
        Run the full multi-engine backtest over *df*.

        Args:
            df:      LTF OHLC DataFrame.  Index may be datetime.
            htf_df:  Optional pre-built HTF DataFrame.  If None, resampled
                     from df using htf_ratio.

        Returns:
            Dict of {signal_source: metrics_dict} for GANN, ICT, ASTRO, and COMBINED.
        """
        if len(df) < max(_GANN_WINDOW, _ICT_WINDOW) + 2:
            raise ValueError(f"df must have at least {max(_GANN_WINDOW, _ICT_WINDOW) + 2} rows")

        # Build HTF if not provided
        if htf_df is None:
            htf_df = df  # fall back to same df when no HTF available

        swing_index = 0  # updated when a new extreme is detected

        for i in range(_GANN_WINDOW, len(df) - 1):
            bar = df.iloc[i]
            next_bar = df.iloc[i + 1]

            # ---- Gann score ----
            gann_candles = _candles_from_df(df, i - _GANN_WINDOW, i)
            gann_result = self.gann.analyze(gann_candles)
            gann_score_raw = gann_result.get("score", 0) or 0
            gann_ok = int(gann_score_raw > 0)

            # Time cycle check
            time_count = time_from_extreme(i, swing_index)
            time_cycles = detect_time_cycle(time_count)
            time_ok = 1 if time_cycles else 0

            # ---- ICT score ----
            ltf_start = max(0, i - _ICT_WINDOW)
            htf_start = max(0, i - _HTF_WINDOW)
            ltf_window = df.iloc[ltf_start: i + 1]
            htf_window = htf_df.iloc[htf_start: i + 1]
            try:
                ict_result = self.ict.analyze(ltf_window, htf_window)
                ict_ok = 1 if ict_result["ict_score"] > 0 else 0
                ict_direction = ict_result["direction"]
            except Exception:
                ict_ok = 0
                ict_direction = "NO_TRADE"

            # ---- Astro score ----
            jd = _jd_from_bar(df, i)
            try:
                astro = astro_score(jd)
                astro_score_raw = int(astro.get("score", 0) or 0)
                astro_ok = 1 if astro_score_raw > 0 else 0
            except Exception:
                astro_score_raw = 0
                astro_ok = 0

            # ---- Price cluster check ----
            delta = price_range(float(bar["high"]), float(bar["low"]))
            levels = project_levels(float(bar["close"]), delta)
            harmonics = sqrt2_levels(float(bar["close"]))
            clusters = detect_clusters(levels + harmonics)
            cluster_ok = 1 if clusters else 0

            # ---- Combined signal ----
            signal = generate_signal(
                time_align=time_ok,
                price_hit=gann_ok,
                geometry_ok=ict_ok,
                structure_ok=astro_ok,
                cluster_ok=cluster_ok,
            )

            if signal == "NO TRADE":
                # Update swing index when no trade
                if float(df["high"].iloc[i]) >= float(df["high"].iloc[max(0, i - 5):i].max()):
                    swing_index = i
                continue

            direction = _resolve_trade_direction(gann_score_raw, ict_direction, astro_score_raw)
            if direction is None:
                continue
            entry = float(bar["close"])
            exit_px = float(next_bar["open"])

            # Record per-engine trades + combined
            for source, ok in [
                ("GANN", gann_ok),
                ("ICT", ict_ok),
                ("ASTRO", astro_ok),
                ("COMBINED", 1),
            ]:
                if source != "COMBINED" and not ok:
                    continue
                self.engine.add_trade(
                    source,
                    Trade(
                        signal_source=source,
                        entry_price=entry,
                        entry_time=i,
                        exit_price=exit_px,
                        exit_time=i + 1,
                        direction=direction,
                    ),
                )

        # ---- Compile results ----
        all_metrics = self.engine.calculate_all_metrics()
        report: dict[str, dict] = {}
        for source, m in all_metrics.items():
            report[source] = {
                "total_trades":    m.total_trades,
                "win_rate":        round(m.win_rate * 100, 2),
                "profit_factor":   round(m.profit_factor, 4) if math.isfinite(m.profit_factor) else "∞",
                "sharpe_ratio":    round(m.sharpe_ratio, 4),
                "max_drawdown_pct": round(m.max_drawdown * 100, 2),
                "net_profit_pips": round(m.net_profit, 2),
                "risk_reward":     round(m.risk_reward_ratio, 2),
            }
        return report
