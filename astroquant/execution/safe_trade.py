from __future__ import annotations


def safe_trade(exec_engine, direction: str, lot_size: float):
    """
    Minimal safe execution wrapper used by orchestrator.

    Returns one of: "SUCCESS", "BLOCKED", "FAILED".
    """
    try:
        side = str(direction or "").upper().strip()
        if side not in {"BUY", "SELL"}:
            return "BLOCKED"

        lot = float(lot_size)
        if lot <= 0:
            return "BLOCKED"

        result = exec_engine.place_trade(side, lot)
        if isinstance(result, str):
            return result
        if result in (True, 1):
            return "SUCCESS"
        return "FAILED"
    except Exception:
        return "FAILED"
