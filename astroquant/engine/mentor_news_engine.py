from __future__ import annotations


class MentorNewsEngine:
    def check(self, market: dict | None = None) -> dict:
        payload = market or {}
        return {
            "next_event": str(payload.get("news_event") or "None"),
            "impact": str(payload.get("news_impact") or "Low"),
            "time": str(payload.get("news_time") or "--"),
        }
