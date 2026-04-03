"""
AstroQuant Advanced Projection Engine
Projects symmetric price levels above and below a base price
using a delta (range) value and configurable multipliers.
"""


def project_levels(
    base_price: float,
    delta: float,
    multipliers: list[float] | None = None,
) -> list[float]:
    """
    Return projected price targets above and below base_price.

    For each multiplier m the engine adds base + m*delta (upside)
    and base - m*delta (downside), giving a symmetric level grid.

    Args:
        base_price: Anchor price (e.g. recent swing high/low).
        delta: Measured move to project (e.g. prior bar range).
        multipliers: List of expansion multiples (default [1, 2, 3]).

    Returns:
        List of projected price levels in insertion order
        [+1x, -1x, +2x, -2x, ...].
    """
    if multipliers is None:
        multipliers = [1, 2, 3]

    base = float(base_price)
    d = float(delta)
    levels: list[float] = []

    for m in multipliers:
        m_f = float(m)
        levels.append(round(base + m_f * d, 6))
        levels.append(round(base - m_f * d, 6))

    return levels
