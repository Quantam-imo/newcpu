from __future__ import annotations


class MentorICTEngine:
    def detect(self, market: dict) -> dict:
        turtle = None
        price = float(market.get("price") or 0.0)
        prev_low = float(market.get("prev_low") or 0.0)
        prev_high = float(market.get("prev_high") or 0.0)

        if prev_low > 0 and price < prev_low:
            turtle = "Buy Turtle Soup"
        elif prev_high > 0 and price > prev_high:
            turtle = "Sell Turtle Soup"

        return {
            "turtle_soup": turtle,
            "fvg_zone": market.get("fvg") or "--",
            "order_block": market.get("ob") or "--",
            "liquidity_sweep": market.get("sweep") or "None",
        }
