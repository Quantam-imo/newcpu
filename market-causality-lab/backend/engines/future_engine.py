def future_engine(state, phase, time_signal, harmonic, numerology):
    prediction = {}

    # Direction logic
    if phase == "ACCUMULATION" and "STRONG TURN WINDOW" in time_signal["timing"]:
        prediction["direction"] = "EXPANSION SOON"

    elif phase == "DISTRIBUTION":
        prediction["direction"] = "REVERSAL SOON"

    else:
        prediction["direction"] = "UNCLEAR"

    # Strength
    strength = 0

    if harmonic["pattern"] != "NONE":
        strength += 1

    if numerology["meaning"] in ["REVERSAL", "COMPLETION"]:
        strength += 1

    if time_signal["timing"] == "STRONG TURN WINDOW":
        strength += 2

    prediction["strength"] = strength

    return prediction