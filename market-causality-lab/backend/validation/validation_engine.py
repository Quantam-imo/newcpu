def validate_signal(confidence, trap, phase):
    if confidence < 0.6:
        return "REJECT"

    if trap["trap"] != "NONE" and phase == "MANIPULATION":
        return "HIGH_QUALITY"

    if confidence > 0.75:
        return "STRONG"

    return "NORMAL"