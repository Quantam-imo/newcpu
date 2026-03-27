ASPECTS = {
    "CONJUNCTION": 0,
    "SEXTILE": 60,
    "SQUARE": 90,
    "TRINE": 120,
    "OPPOSITION": 180
}

ORB = 3  # tolerance

def get_aspects(planets):
    aspects = []
    keys = list(planets.keys())
    for i in range(len(keys)):
        for j in range(i+1, len(keys)):
            p1, p2 = keys[i], keys[j]
            diff = abs(planets[p1] - planets[p2])
            for name, angle in ASPECTS.items():
                if abs(diff - angle) <= ORB:
                    aspects.append((p1, p2, name))
    return aspects
