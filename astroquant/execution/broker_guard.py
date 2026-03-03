from __future__ import annotations


class BrokerGuard:

    @staticmethod
    def spread_ok(bid: float, ask: float, max_spread: float) -> bool:
        spread = float(ask) - float(bid)
        return spread <= float(max_spread)

    @staticmethod
    def price_sync_ok(futures_price: float, broker_price: float, tolerance: float) -> bool:
        return abs(float(futures_price) - float(broker_price)) <= float(tolerance)

    @staticmethod
    def phase_drawdown_ok(current_dd: float, max_dd: float) -> bool:
        return float(current_dd) < float(max_dd)

    @staticmethod
    def notional_spread(bid: float, ask: float) -> float:
        return float(ask) - float(bid)

    @staticmethod
    def bps_divergence(reference_price: float, compared_price: float) -> float:
        midpoint = (float(reference_price) + float(compared_price)) / 2.0
        if midpoint <= 0:
            return 0.0
        return abs((float(reference_price) - float(compared_price)) / midpoint) * 10000.0
