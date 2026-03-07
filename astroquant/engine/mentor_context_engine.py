from __future__ import annotations


class MentorContextEngine:
    def analyze(self, market: dict) -> dict:
        return {
            "symbol": market.get("symbol") or "--",
            "price": float(market.get("price") or 0.0),
            "prev_low": float(market.get("prev_low") or 0.0),
            "prev_high": float(market.get("prev_high") or 0.0),
            "htf_bias": str(market.get("htf_bias") or "NEUTRAL"),
            "ltf_structure": str(market.get("ltf_structure") or "RANGE"),
            "kill_zone": str(market.get("kill_zone") or "Inactive"),
            "volatility": str(market.get("volatility") or "NORMAL"),
        }
