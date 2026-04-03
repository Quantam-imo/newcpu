"""
AstroQuant Core Cycle Engine
Intraday and swing-level Gann cycle detection helpers.
"""


def detect_intraday_cycles(index: int) -> list[int]:
    """
    Return active intraday Gann cycles (3, 6, 9) when the bar index
    is divisible by 3.
    """
    return [3, 6, 9] if int(index) % 3 == 0 else []


def detect_swing_cycles(index: int) -> list[int]:
    """
    Return active swing Gann cycles (45, 90) when the bar index
    is divisible by 45.
    """
    return [45, 90] if int(index) % 45 == 0 else []


def cycle_confluence(time_cycles: list) -> bool:
    """
    Return True when two or more distinct cycle signals are active
    simultaneously — a classic Gann confluence rule.
    """
    return len(time_cycles) >= 2
