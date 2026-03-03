class OrderflowEngine:

    def analyze(self, candles):
        if not candles or len(candles) < 5:
            return {
                "delta": 0.0,
                "delta_positive": False,
                "absorption": False,
                "volume_spike": False,
                "liquidity_sweep": False,
                "volatility_breakout": False,
            }

        recent = candles[-20:] if len(candles) >= 20 else candles
        last = candles[-1]

        ranges = [max(0.0, float(c["high"]) - float(c["low"])) for c in recent]
        avg_range = (sum(ranges[:-1]) / max(1, len(ranges) - 1)) if len(ranges) > 1 else ranges[-1]
        last_range = ranges[-1]

        volumes = [max(0.0, float(c.get("volume", 0.0))) for c in recent]
        avg_volume = (sum(volumes[:-1]) / max(1, len(volumes) - 1)) if len(volumes) > 1 else volumes[-1]
        last_volume = volumes[-1]

        signed_deltas = []
        for candle in recent:
            open_price = float(candle["open"])
            close_price = float(candle["close"])
            volume = max(0.0, float(candle.get("volume", 0.0)))
            direction = 1.0 if close_price >= open_price else -1.0
            body = abs(close_price - open_price)
            signed_deltas.append(direction * max(body, 1e-9) * max(volume, 1.0))

        delta_value = float(sum(signed_deltas[-5:]))
        delta_positive = delta_value >= 0

        body_last = abs(float(last["close"]) - float(last["open"]))
        body_to_range = (body_last / last_range) if last_range > 0 else 1.0
        volume_spike = last_volume > (avg_volume * 1.35 if avg_volume > 0 else last_volume + 1)
        absorption = bool(volume_spike and body_to_range <= 0.35)

        prev_high = max(float(c["high"]) for c in candles[-6:-1])
        prev_low = min(float(c["low"]) for c in candles[-6:-1])
        liquidity_sweep = float(last["high"]) > prev_high or float(last["low"]) < prev_low

        volatility_breakout = bool(avg_range > 0 and last_range > (avg_range * 1.6))

        return {
            "delta": delta_value,
            "delta_positive": delta_positive,
            "absorption": absorption,
            "volume_spike": volume_spike,
            "liquidity_sweep": liquidity_sweep,
            "volatility_breakout": volatility_breakout,
        }
