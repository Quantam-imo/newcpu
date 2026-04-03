import os
import swisseph as swe
from datetime import datetime

# Resolve the ephe data directory relative to this file so the path is stable
# regardless of the working directory at runtime.
# Falls back to Moshier (built-in) if the directory does not exist.
_EPHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "ephe")
if os.path.isdir(_EPHE_DIR):
    swe.set_ephe_path(os.path.realpath(_EPHE_DIR))
# else: swisseph silently uses the built-in Moshier ephemeris

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
