from __future__ import annotations

try:
    from config.production_config import ProductionConfig
except Exception:  # pragma: no cover - fallback for package-style imports
    from astroquant.config.production_config import ProductionConfig


class SafetyGuardEngine:
    def check_spread(self, spread):
        try:
            return float(spread) <= float(ProductionConfig.MAX_SPREAD)
        except Exception:
            return False

    def check_slippage(self, expected_price, executed_price):
        try:
            slippage = abs(float(expected_price) - float(executed_price))
            return slippage <= float(ProductionConfig.MAX_SLIPPAGE)
        except Exception:
            return False

    def check_trade_frequency(self, trades_today):
        try:
            return int(trades_today) < int(ProductionConfig.MAX_TRADES_PER_DAY)
        except Exception:
            return False

    def check_volume(self, volume):
        try:
            return float(volume) >= float(ProductionConfig.MIN_VOLUME)
        except Exception:
            return False

    def check_trading_enabled(self):
        return bool(ProductionConfig.TRADING_ENABLED)

    def check_data_delay(self, delay_seconds):
        try:
            return float(delay_seconds) <= float(ProductionConfig.MAX_DATA_DELAY)
        except Exception:
            return False

    def check_lot_size(self, symbol, lot_size):
        symbol_key = str(symbol or "").upper().strip()
        caps = dict(getattr(ProductionConfig, "SYMBOL_MAX_LOT", {}) or {})
        if symbol_key == "BTCUSD":
            symbol_key = "BTC"
        cap = float(caps.get(symbol_key, 0.0) or 0.0)
        if cap <= 0.0:
            return True
        try:
            return float(lot_size) <= cap
        except Exception:
            return False
