def final_engine(
    state,
    phase,
    psychology,
    trap,
    behavior,
    dominant,
    confidence,
    scenarios,
    time_signal,
):
    return {
        "phase": phase,
        "trend": state["trend"],
        "psychology": psychology["emotion"],
        "trap": trap["trap"],
        "behavior": behavior["next"],
        "decision": dominant,
        "confidence": confidence,
        "timing": time_signal["timing"],
        "scenarios": scenarios,
    }