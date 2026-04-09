def future_engine(state, phase, time_signal, harmonic, numerology):
    """
    Identify Gann cycle phase and project near-term direction.
    Produces human-readable cycle identification markers.
    """
    prediction = {}

    # ── Numerology meaning → cycle energy ────────────────────────────────────
    num_meaning = str(numerology.get("meaning") or "").upper()
    timing      = str(time_signal.get("timing") or "").upper()
    harmonic_pattern = str(harmonic.get("pattern") or "NONE").upper()

    is_strong_time   = "STRONG TURN" in timing
    is_turn_window   = "TURN WINDOW" in timing
    is_expansion_num = num_meaning in ("START", "EXPANSION", "POWER")
    is_reversal_num  = num_meaning in ("REVERSAL", "COMPLETION", "CHANGE")

    # ── Gann cycle identification ─────────────────────────────────────────────
    # Map phase + numerology → Gann cycle identification label
    if phase == "ACCUMULATION":
        if is_strong_time or is_expansion_num:
            prediction["direction"] = "EXPANSION STARTING"
            prediction["cycle_event"] = "CYCLE STARTED — Accumulation complete, markup imminent"
        else:
            prediction["direction"] = "ACCUMULATION ONGOING"
            prediction["cycle_event"] = "CYCLE IN PROGRESS — Price absorbing supply"

    elif phase == "MARKUP":
        if is_reversal_num or is_strong_time:
            prediction["direction"] = "DISTRIBUTION APPROACHING"
            prediction["cycle_event"] = "CYCLE PEAK NEAR — Distribution zone forming"
        else:
            prediction["direction"] = "MARKUP CONTINUATION"
            prediction["cycle_event"] = "MARKUP PHASE ACTIVE — Trend continuation expected"

    elif phase == "DISTRIBUTION":
        if is_strong_time or is_reversal_num:
            prediction["direction"] = "REVERSAL SOON"
            prediction["cycle_event"] = "CYCLE TOP — Reversal setup in progress"
        else:
            prediction["direction"] = "DISTRIBUTION ONGOING"
            prediction["cycle_event"] = "DISTRIBUTION PHASE — Supply entering market"

    elif phase == "MARKDOWN":
        if is_expansion_num or is_strong_time:
            prediction["direction"] = "BOTTOM FORMING"
            prediction["cycle_event"] = "CYCLE BOTTOM NEAR — Markdown exhausting"
        else:
            prediction["direction"] = "MARKDOWN CONTINUATION"
            prediction["cycle_event"] = "MARKDOWN PHASE ACTIVE — Decline continuing"

    elif phase in ("CONSOLIDATION", "NEUTRAL"):
        if is_strong_time:
            prediction["direction"] = "BREAKOUT IMMINENT"
            prediction["cycle_event"] = "COIL PHASE — Energy compressing, breakout near"
        else:
            prediction["direction"] = "SIDEWAYS"
            prediction["cycle_event"] = "CONSOLIDATION PHASE — Range-bound, await breakout"

    elif phase == "EXPANSION":
        # Expansion = MARKUP phase in Gann/Wyckoff vocabulary
        if is_reversal_num or is_strong_time:
            prediction["direction"] = "EXPANSION PEAK NEAR"
            prediction["cycle_event"] = "EXPANSION PEAK — Momentum crest, watch for reversal"
        elif is_expansion_num:
            prediction["direction"] = "EXPANSION CONTINUATION"
            prediction["cycle_event"] = "EXPANSION PHASE ACTIVE — Markup in full force"
        else:
            prediction["direction"] = "MARKUP CONTINUATION"
            prediction["cycle_event"] = "MARKUP PHASE — Trend extended, momentum carrying"

    elif phase == "MANIPULATION":
        # Smart money sweep — anticipate the reversal after the trap
        if is_expansion_num or is_strong_time:
            prediction["direction"] = "REVERSAL AFTER SWEEP"
            prediction["cycle_event"] = "MANIPULATION DETECTED — Sweep complete, reversal imminent"
        else:
            prediction["direction"] = "TRAP FORMING"
            prediction["cycle_event"] = "LIQUIDITY SWEEP — False breakout, await confirmation"

    else:
        # Unknown phase — map to CONSOLIDATION conservatively
        prediction["direction"] = "MONITOR"
        prediction["cycle_event"] = f"PHASE={phase} — Gann cycle building, await trigger"

    # ── Strength scoring ──────────────────────────────────────────────────────
    strength = 0

    if harmonic_pattern != "NONE":
        strength += 1  # Harmonic pattern confirms cycle

    if is_reversal_num or is_expansion_num:
        strength += 1  # Numerology aligns

    if is_strong_time:
        strength += 2  # Time window is critical
    elif is_turn_window:
        strength += 1

    if phase in ("ACCUMULATION", "DISTRIBUTION"):
        strength += 1  # Phase transition zones are high probability

    prediction["strength"] = min(4, strength)

    # ── Cycle progress description ────────────────────────────────────────────
    phase_pct = {
        "ACCUMULATION": 10, "MARKUP": 35, "DISTRIBUTION": 60,
        "MARKDOWN": 80, "CONSOLIDATION": 50, "NEUTRAL": 50,
        "EXPANSION": 40, "MANIPULATION": 20,
    }
    prediction["cycle_progress_pct"] = phase_pct.get(phase, 50)
    prediction["numerology_energy"] = num_meaning if num_meaning else "NEUTRAL"
    prediction["timing_window"] = timing if timing else "NORMAL"

    return prediction