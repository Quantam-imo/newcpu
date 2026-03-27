# Legacy trade execution helper — wired to PlaywrightEngine via matchtrader_executor
from astroquant.execution.matchtrader_executor import MatchTraderExecutor, MatchTraderConfig

_executor: MatchTraderExecutor | None = None


def _get_executor() -> MatchTraderExecutor:
    global _executor
    if _executor is None:
        _executor = MatchTraderExecutor(MatchTraderConfig())
    return _executor


def place_order(trade: dict) -> dict:
    """Submit a trade dict to the live broker via MatchTraderExecutor."""
    try:
        executor = _get_executor()
        return executor.place_order(trade)
    except Exception as exc:
        print(f"[trade_execution] place_order failed: {exc}")
        return {"status": "error", "reason": str(exc)}


def execute_trade(signal: dict, price: float) -> dict:
    trade: dict = {}
    if signal["action"] == "BUY":
        trade = {"entry": price, "sl": price - 20, "tp": price + 60}
    elif signal["action"] == "SELL":
        trade = {"entry": price, "sl": price + 20, "tp": price - 60}
    place_order(trade)
    return trade
