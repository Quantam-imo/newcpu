def get_aspects(planets):
    aspects = []
    keys = list(planets.keys())
    for i in range(len(keys)):
        for j in range(i+1, len(keys)):
            p1 = keys[i]
            p2 = keys[j]
            angle = abs(planets[p1] - planets[p2])
            if abs(angle - 0) < 5:
                aspects.append((p1, p2, "CONJUNCTION"))
            elif abs(angle - 90) < 5:
                aspects.append((p1, p2, "SQUARE"))
            elif abs(angle - 180) < 5:
                aspects.append((p1, p2, "OPPOSITION"))
    return aspects
