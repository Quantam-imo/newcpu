def detect_retrograde(speeds):
    retro = {}
    for planet, speed in speeds.items():
        retro[planet] = speed < 0
    return retro
