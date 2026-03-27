def astro_engine(df):
    # Simple cycle simulation (upgrade later with real ephemeris)
    cycle = len(df) % 27  # 27 nakshatra cycle

    if cycle in [0, 9, 18]:
        strength = "HIGH"
    else:
        strength = "NORMAL"

    return {"nakshatra_cycle": cycle, "strength": strength}