def physics_engine(state):
    force = abs(state["momentum"])
    velocity = state["momentum"]
    # Threshold calibrated for XAU/USD 1h (median 10-bar H-L range ≈ $5.70)
    energy = "HIGH" if state["volatility"] > 5 else "LOW"

    return {"force": force, "velocity": velocity, "energy": energy}