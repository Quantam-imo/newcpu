from __future__ import annotations


class ProductionConfig:
    # Trading limits
    MAX_RISK_PER_TRADE = 0.005
    MAX_DAILY_LOSS = 0.03
    MAX_TOTAL_DRAWDOWN = 0.08

    # Execution safety
    MAX_SLIPPAGE = 3.0
    MAX_SPREAD = 5.0

    # Trading limits
    MAX_TRADES_PER_DAY = 10

    # Market filters
    MIN_VOLUME = 50

    # System health
    MAX_DATA_DELAY = 10

    # Enable / disable trading
    TRADING_ENABLED = True

    # Optional symbol-level lot caps for production guardrails.
    SYMBOL_MAX_LOT = {
        "XAUUSD": 0.50,
        "EURUSD": 1.00,
        "NQ": 1.00,
        "US30": 1.00,
        "BTC": 0.05,
        "BTCUSD": 0.05,
    }
