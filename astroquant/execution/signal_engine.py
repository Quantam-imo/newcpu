"""
AstroQuant Execution Signal Engine
Combines time, price, geometry, structure, and cluster alignment
scores into a single actionable trade signal.

Each boolean input contributes 1 point to the score:
  >= 4 → STRONG TRADE
  >= 3 → WEAK TRADE
      → NO TRADE
"""


def generate_signal(
    time_align: bool | int,
    price_hit: bool | int,
    geometry_ok: bool | int,
    structure_ok: bool | int,
    cluster_ok: bool | int,
) -> str:
    """
    Return a trade signal string based on the number of confluent conditions met.

    Args:
        time_align:  Gann time cycle is active at current bar.
        price_hit:   Price is at or near a key projected level.
        geometry_ok: Gann angle / fan line alignment confirmed.
        structure_ok: Market structure (swing/trend) supports the setup.
        cluster_ok:  Multiple harmonic/projection levels clustered nearby.

    Returns:
        "STRONG TRADE", "WEAK TRADE", or "NO TRADE"
    """
    score = int(bool(time_align)) + int(bool(price_hit)) + \
            int(bool(geometry_ok)) + int(bool(structure_ok)) + \
            int(bool(cluster_ok))

    if score >= 4:
        return "STRONG TRADE"
    if score >= 3:
        return "WEAK TRADE"
    return "NO TRADE"
