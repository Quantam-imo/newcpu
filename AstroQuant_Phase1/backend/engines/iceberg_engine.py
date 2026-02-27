class IcebergEngine:

    def analyze(self, symbol, orderflow_data):
        buy_pressure = float(orderflow_data.get("buy_volume", 0) or 0)
        sell_pressure = float(orderflow_data.get("sell_volume", 0) or 0)

        pressure = "Buying" if buy_pressure > sell_pressure else "Selling"

        low = float(orderflow_data.get("low", 0) or 0)
        high = float(orderflow_data.get("high", 0) or 0)
        zone = f"{round(low, 2)}-{round(high, 2)}"

        return {
            "buy_count": int(max(0, buy_pressure) / 100),
            "sell_count": int(max(0, sell_pressure) / 100),
            "zone": zone,
            "pressure": pressure,
        }
