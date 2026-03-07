from __future__ import annotations


class MentorAstroEngine:
    def calculate(self, market: dict | None = None) -> dict:
        payload = market or {}
        return {
            "harmonic_window": bool(payload.get("astro_window_active", True)),
            "planet_event": payload.get("astro_marker") or "Mars Square Saturn",
            "bias": str(payload.get("astro_bias") or "Volatility"),
        }
