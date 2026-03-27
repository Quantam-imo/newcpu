import swisseph as swe
from datetime import datetime

# Set ephemeris path (ensure ./ephe exists and contains Swiss Ephemeris files)
swe.set_ephe_path("./ephe")

PLANETS = {
    "sun": swe.SUN,
    "moon": swe.MOON,
    "mercury": swe.MERCURY,
    "venus": swe.VENUS,
    "mars": swe.MARS,
    "jupiter": swe.JUPITER,
    "saturn": swe.SATURN
}

def get_planets():
    now = datetime.utcnow()
    jd = swe.julday(
        now.year, now.month, now.day,
        now.hour + now.minute / 60
    )
    positions = {}
    speeds = {}
    for name, p in PLANETS.items():
        data = swe.calc_ut(jd, p)
        positions[name] = data[0][0]   # degree
        speeds[name] = data[0][3]      # speed
    return positions, speeds
