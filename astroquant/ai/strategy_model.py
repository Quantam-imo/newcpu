import random

def strategy_score(ict, gann, astro):
    score = 0

    if ict["signal"] == "BUY":
        score += 2
    if gann == "BUY":
        score += 1
    if astro == "BUY":
        score += 1

    return {
        "score": score,
        "confidence": min(score * 25, 100)
    }
