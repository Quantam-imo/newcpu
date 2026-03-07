from __future__ import annotations


class MentorLiquidityEngine:
    def analyze(self, market: dict) -> dict:
        return {
            "external_high": float(market.get("external_high") or market.get("prev_high") or 0.0),
            "external_low": float(market.get("external_low") or market.get("prev_low") or 0.0),
            "sweep": str(market.get("sweep") or "None"),
            "target": str(market.get("liquidity_target") or "external_high"),
        }
