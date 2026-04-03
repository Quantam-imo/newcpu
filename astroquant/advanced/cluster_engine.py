"""
AstroQuant Advanced Cluster Engine
Identifies price clusters where multiple projected levels converge
within a tolerance band — a key Gann/harmonic confirmation filter.
"""


def detect_clusters(
    levels: list[float],
    tolerance: float = 2.0,
) -> list[tuple[float, float]]:
    """
    Find adjacent level pairs that are within *tolerance* of each other.

    A cluster signals a high-probability support/resistance zone where
    projection, harmonic, and geometry levels overlap.

    Args:
        levels: Combined list of price levels (projections + harmonics).
        tolerance: Maximum price distance to consider two levels clustered.

    Returns:
        List of (level_a, level_b) tuples forming a cluster pair.
    """
    if not levels:
        return []

    sorted_levels = sorted(float(x) for x in levels)
    clusters: list[tuple[float, float]] = []

    for i in range(len(sorted_levels) - 1):
        a = sorted_levels[i]
        b = sorted_levels[i + 1]
        if abs(b - a) <= float(tolerance):
            clusters.append((a, b))

    return clusters
