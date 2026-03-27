from astroquant.engine.astro_planets import get_planet_positions
from astroquant.engine.astro_aspects import get_aspects

def get_astro_signal():
    planets = get_planet_positions()
    aspects = get_aspects(planets)
    score_buy = 0
    score_sell = 0
    for a in aspects:
        p1, p2, aspect = a
        # Example logic (expand later)
        if aspect == "CONJUNCTION":
            score_buy += 1
        elif aspect == "OPPOSITION":
            score_sell += 1
        elif aspect == "SQUARE":
            score_sell += 1
    if score_buy > score_sell:
        return "BUY"
    elif score_sell > score_buy:
        return "SELL"
    return "NEUTRAL"
