from __future__ import annotations


class MentorSessionEngine:
    def analyze(self, market: dict) -> dict:
        session = str(market.get("session") or "Transition")
        if session == "Asia":
            phase = "Accumulation"
        elif session in ("London", "Europe"):
            phase = "Manipulation"
        elif session in ("NewYork", "US"):
            phase = "Distribution"
        else:
            phase = "Transition"
        return {"session": session, "phase": phase}
