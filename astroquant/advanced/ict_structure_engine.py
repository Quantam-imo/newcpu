"""
AstroQuant Advanced ICT Structure Engine
=========================================
Unified wrapper around ict_engine.py and ict_engine_pro.py.

Exposes a single ICTStructureEngine class with:
  - analyze(df, htf_df)  → structured dict compatible with generate_signal()
  - score()              → int used directly in generate_signal()

All underlying ICT functions remain importable from their original modules;
this class just ties them together for the signal pipeline.
"""
from __future__ import annotations

import pandas as pd

from astroquant.engine.ict_engine import (
    detect_structure,
    detect_liquidity_sweep,
    detect_fvg,
    detect_order_block,
)
from astroquant.engine.ict_engine_pro import (
    get_htf_bias,
    get_pd_zone,
    detect_liquidity_pool,
    killzone_filter,
    detect_smt,
    entry_model,
)


class ICTStructureEngine:
    """
    Single entry-point for all ICT confluence checks.

    Usage:
        engine = ICTStructureEngine()
        result = engine.analyze(ltf_df, htf_df, current_hour=14)
        signal_score = result["ict_score"]   # plug into generate_signal()
    """

    def analyze(
        self,
        df: pd.DataFrame,
        htf_df: pd.DataFrame | None = None,
        current_hour: int | None = None,
        secondary_df: pd.DataFrame | None = None,
    ) -> dict:
        """
        Run all ICT checks against the supplied DataFrames.

        Args:
            df:            LTF (lower timeframe) OHLC DataFrame.
            htf_df:        HTF DataFrame for bias.  Falls back to df if None.
            current_hour:  UTC hour (0-23) for killzone filter.  Auto-detected if None.
            secondary_df:  Second instrument (e.g. DXY) for SMT divergence.

        Returns:
            {
                "structure":       str,   # BOS_BULLISH | BOS_BEARISH | RANGE
                "liquidity_sweep": str | None,
                "fvg":             dict | None,
                "order_block":     dict | None,
                "htf_bias":        str,   # BULLISH | BEARISH | RANGE
                "pd_zone":         str,   # PREMIUM | DISCOUNT
                "liquidity_pool":  str | None,
                "killzone":        str,
                "smt":             str | None,
                "entry_model":     dict,
                "ict_score":       int,   # net score → plug into generate_signal()
                "direction":       str,   # BUY | SELL | NO_TRADE
            }
        """
        if htf_df is None:
            htf_df = df

        if current_hour is None:
            from datetime import datetime, timezone
            current_hour = datetime.now(timezone.utc).hour

        # --- LTF checks ---
        structure = detect_structure(df)
        sweep = detect_liquidity_sweep(df)
        fvg = detect_fvg(df)
        ob = detect_order_block(df)

        # --- HTF / pro checks ---
        htf_bias = get_htf_bias(htf_df)
        pd_zone = get_pd_zone(df)
        liq_pool = detect_liquidity_pool(df)
        killzone = killzone_filter(current_hour)
        smt = detect_smt(df, secondary_df) if secondary_df is not None else None

        # --- Entry model ---
        model = entry_model(
            htf_bias=htf_bias,
            pd_zone=pd_zone,
            liquidity=sweep,
            smt=smt,
            killzone=killzone,
        )

        # --- Net score: >0 = bullish, <0 = bearish ---
        score = 0
        if "BULLISH" in structure:
            score += 1
        if "BEARISH" in structure:
            score -= 1
        if htf_bias == "BULLISH":
            score += 2
        elif htf_bias == "BEARISH":
            score -= 2
        if pd_zone == "DISCOUNT":
            score += 1
        elif pd_zone == "PREMIUM":
            score -= 1
        if fvg:
            score += 1 if "BULLISH" in fvg.get("type", "") else -1
        if ob:
            score += 1 if "BULLISH" in ob.get("type", "") else -1
        if sweep == "BUY_SIDE_LIQUIDITY_TAKEN":
            score -= 1
        elif sweep == "SELL_SIDE_LIQUIDITY_TAKEN":
            score += 1
        if killzone in ("LONDON_KILLZONE", "NY_KILLZONE"):
            score += 1          # session confirmation bonus
        if smt == "BULLISH_SMT":
            score += 1
        elif smt == "BEARISH_SMT":
            score -= 1

        direction = "NO_TRADE"
        if score >= 3:
            direction = "BUY"
        elif score <= -3:
            direction = "SELL"

        return {
            "structure": structure,
            "liquidity_sweep": sweep,
            "fvg": fvg,
            "order_block": ob,
            "htf_bias": htf_bias,
            "pd_zone": pd_zone,
            "liquidity_pool": liq_pool,
            "killzone": killzone,
            "smt": smt,
            "entry_model": model or {},
            "ict_score": score,
            "direction": direction,
        }

    def score(self, df: pd.DataFrame, htf_df: pd.DataFrame | None = None) -> int:
        """Convenience method — returns just the net ict_score integer."""
        return self.analyze(df, htf_df)["ict_score"]
