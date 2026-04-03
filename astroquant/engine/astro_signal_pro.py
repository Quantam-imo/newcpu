from astroquant.engine.astro_swiss import get_planets
from astroquant.engine.astro_aspects_pro import get_aspects
from astroquant.engine.astro_360_panel import calculate_cycle


def detect_retrograde(speeds: dict) -> dict:
    """Return a dict of planet→bool indicating retrograde (negative speed)."""
    return {planet: float(speed) < 0.0 for planet, speed in speeds.items()}


def get_astro_signal() -> str:
    """
    Compute a BUY / SELL / NEUTRAL signal from live planetary data.

    Scoring:
      TRINE        → +2 buy
      SQUARE       → +2 sell
      OPPOSITION   → +1 sell
      Mercury retro → +1 sell
      Mars-Saturn <30° separation → +1 buy
    """
    planets, speeds = get_planets()
    aspects = get_aspects(planets)
    retro = detect_retrograde(speeds)
    score_buy = 0
    score_sell = 0

    for p1, p2, aspect in aspects:
        if aspect == "TRINE":
            score_buy += 2
        elif aspect == "SQUARE":
            score_sell += 2
        elif aspect == "OPPOSITION":
            score_sell += 1

    if retro.get("mercury"):
        score_sell += 1

    cycle = calculate_cycle(planets["mars"], planets["saturn"])
    if cycle and cycle["angle_diff"] < 30:
        score_buy += 1

    if score_buy > score_sell:
        return "BUY"
    if score_sell > score_buy:
        return "SELL"
    return "NEUTRAL"
