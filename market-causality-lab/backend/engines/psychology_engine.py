def psychology_engine(state, phase):
    # Default
    emotion = "NEUTRAL"

    if phase == "ACCUMULATION":
        emotion = "CONFUSION"

    elif phase == "MANIPULATION":
        emotion = "FRUSTRATION"

    elif phase == "EXPANSION":
        if state["trend"] == "UP":
            emotion = "FOMO (BUYERS)"
        else:
            emotion = "PANIC (SELLERS)"

    elif phase == "DISTRIBUTION":
        emotion = "OVERCONFIDENCE"

    return {"emotion": emotion}