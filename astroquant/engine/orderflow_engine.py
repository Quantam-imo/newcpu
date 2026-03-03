import databento as db
from collections import defaultdict


class OrderflowEngine:

    def __init__(self, api_key):
        self.client = db.Historical(api_key) if api_key else None

    def get_recent_trades(self, dataset, symbol):
        if not self.client:
            return []

        try:
            trades = self.client.timeseries.get_range(
                dataset=dataset,
                schema="trades",
                symbols=[symbol],
                limit=500,
            )
        except Exception:
            return []

        return trades

    def calculate_delta(self, trades):
        buy_volume = 0
        sell_volume = 0

        for t in trades:
            side = str(getattr(t, "side", "")).upper()
            size = float(getattr(t, "size", 0) or 0)
            if side == "B":
                buy_volume += size
            else:
                sell_volume += size

        delta = buy_volume - sell_volume

        return delta, buy_volume, sell_volume

    def detect_absorption(self, trades):
        price_volume = defaultdict(int)

        for t in trades:
            price = getattr(t, "price", None)
            size = int(getattr(t, "size", 0) or 0)
            if price is None:
                continue
            price_volume[price] += size

        absorption_levels = []

        for price, volume in price_volume.items():
            if volume > 200:  # institutional threshold
                absorption_levels.append(price)

        return absorption_levels
