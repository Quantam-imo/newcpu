def time_engine(gann, astro, gann_nodes=None):
    signals = []

    if gann["price_time_equal"]:
        signals.append("GANN TURN")

    if astro["strength"] == "HIGH":
        signals.append("ASTRO WINDOW")

    # Node convergence: time + price both at SQ9 spiral node
    if gann_nodes and gann_nodes.get("node_active"):
        signals.append(f"NODE {gann_nodes.get('node_type', 'CARDINAL')}")

    # Time-only harmonic firing (no price node yet, but cycle count hit)
    if gann_nodes and gann_nodes.get("time_at_node") and not gann_nodes.get("node_active"):
        signals.append("TIME HARMONIC")

    if len(signals) >= 2:
        timing = "STRONG TURN WINDOW"
    elif len(signals) == 1:
        timing = "POSSIBLE TURN"
    else:
        timing = "NO SIGNAL"

    return {"signals": signals, "timing": timing}