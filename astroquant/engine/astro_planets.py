import swisseph as swe
from datetime import datetime

def get_planet_positions(jd=None):
    """
    Returns geocentric ecliptic longitudes for major planets using Swiss Ephemeris.
    jd: Julian day (float). If None, uses current UTC.
    """
    if jd is None:
        now = datetime.utcnow()
        jd = swe.julday(now.year, now.month, now.day, now.hour + now.minute/60.0 + now.second/3600.0)
    planets = {
        "sun": swe.SUN,
        "moon": swe.MOON,
        "mercury": swe.MERCURY,
        "venus": swe.VENUS,
        "mars": swe.MARS,
        "jupiter": swe.JUPITER,
        "saturn": swe.SATURN
    }
    positions = {}
    for name, pid in planets.items():
        calc_result = swe.calc_ut(jd, pid)
        lon, lat, dist = calc_result[0][0:3]
        positions[name] = lon
    return positions
