from __future__ import annotations


class MentorProbabilityEngine:
    def score(self, context: dict, liq: dict, inst: dict, ict: dict, gann: dict, astro: dict, news: dict) -> dict:
        score = 0
        if ict.get("turtle_soup"):
            score += 20
        if float(inst.get("delta") or 0.0) > 0:
            score += 10
        if float(inst.get("iceberg_buy") or 0.0) > float(inst.get("iceberg_sell") or 0.0):
            score += 10
        if int(gann.get("cycle") or 0) > 0:
            score += 10
        if bool(astro.get("harmonic_window")):
            score += 5
        if str(news.get("impact") or "").lower() == "high":
            score -= 5
        if str(liq.get("sweep") or "").lower() not in ("none", "", "null"):
            score += 5

        score = max(0, min(100, score))
        if score >= 70:
            verdict = "High Probability Institutional Setup"
        elif score >= 50:
            verdict = "Moderate Probability Setup"
        else:
            verdict = "Low Probability / Wait"
        return {"score": score, "verdict": verdict}
