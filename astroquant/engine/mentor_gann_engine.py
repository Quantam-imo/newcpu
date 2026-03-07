from __future__ import annotations


class MentorGannEngine:
    def calculate(self, market: dict) -> dict:
        base = float(market.get("range") or 0.0)
        low = float(market.get("low") or 0.0)
        return {
            "cycle": int(market.get("bar_count") or 0),
            "target_100": low + base if base > 0 else 0.0,
            "target_200": low + (base * 2.0) if base > 0 else 0.0,
        }
