from astroquant.backend.config import ACCOUNT_CONFIG


def get_daily_loss() -> float:
    """Return current session daily P&L loss (positive = loss) from the runtime runner."""
    try:
        from astroquant.backend.runtime import get_runner
        runner = get_runner()
        if runner is not None and hasattr(runner, "get_daily_pnl"):
            pnl = runner.get_daily_pnl()
            if pnl is not None:
                return max(0.0, float(-pnl))  # losses are negative pnl
    except Exception:
        pass
    return 0.0


def allow_trade() -> bool:
    """Return True if daily loss is within the configured daily limit."""
    daily_loss = get_daily_loss()
    limit = float(ACCOUNT_CONFIG.get("daily_limit", 1500))
    if daily_loss >= limit:
        return False
    return True
