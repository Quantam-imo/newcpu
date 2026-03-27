def calculate_cycle(p1_deg, p2_deg):
    delta = abs(p1_deg - p2_deg)
    if delta == 0:
        return None
    T = 360 / delta
    return {
        "angle_diff": delta,
        "cycle_strength": T
    }
