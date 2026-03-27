def behavior_engine(psychology, trap):
    behavior = {}

    emotion = psychology["emotion"]

    if "CONFUSION" in emotion:
        behavior["next"] = "SIDEWAYS / OVERTRADING"

    elif "FRUSTRATION" in emotion:
        behavior["next"] = "WRONG ENTRIES"

    elif "FOMO" in emotion:
        behavior["next"] = "LATE BUYING"

    elif "PANIC" in emotion:
        behavior["next"] = "FORCED SELLING"

    elif "OVERCONFIDENCE" in emotion:
        behavior["next"] = "OVERLEVERAGE"

    else:
        behavior["next"] = "BALANCED"

    if trap["trap"] != "NONE":
        behavior["next"] = "TRAPPED"

    return behavior