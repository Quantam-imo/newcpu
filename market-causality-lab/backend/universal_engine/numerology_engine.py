from __future__ import annotations


NUMEROLOGY_MEANING = {
    1: "START",
    2: "BALANCE",
    3: "EXPANSION",
    4: "STRUCTURE",
    5: "CHANGE",
    6: "HARMONY",
    7: "REVERSAL",
    8: "POWER",
    9: "COMPLETION",
}


def numerology_number(value: float) -> int:
    """Reduce absolute numeric value to a 1-9 root vibration."""
    digits = [int(ch) for ch in str(int(abs(value))) if ch.isdigit()]
    if not digits:
        return 1
    num = sum(digits)
    while num > 9:
        num = sum(int(ch) for ch in str(num))
    return max(1, num)


def numerology_profile(value: float) -> dict:
    number = numerology_number(value)
    return {
        "number": number,
        "meaning": NUMEROLOGY_MEANING[number],
    }