
class AIMentor:

    def structured(self, fusion, iceberg, ict, gann, astro, news=None):
        direction = str(fusion.get("direction", "BUY")).upper()
        trend = "Bullish" if direction == "BUY" else "Bearish"

        liquidity_label = "Balanced liquidity"
        if ict.get("fvg"):
            liquidity_label = "Fair-value gap active"
        elif ict.get("ict_direction"):
            liquidity_label = f"{str(ict.get('ict_direction')).upper()} structure"

        context = {
            "trend": trend,
            "liquidity": liquidity_label,
            "bias": f"{direction}-side continuation"
        }

        # Active Model
        active_model = fusion.get("active_model", "Fusion")

        # Confidence Breakdown
        confidence_breakdown = {
            "ICT": ict.get("ict_score", 0),
            "Iceberg": iceberg["confidence"] if iceberg else 0,
            "Gann": gann.get("gann_score", 0),
            "Astro": astro.get("astro_score", 0),
            "Final": fusion.get("confidence", 0)
        }

        # Iceberg Template
        iceberg_template = None
        if iceberg:
            base_conf = int(iceberg.get("confidence", 0) or 0)
            buy_volume = max(10, base_conf * 5)
            sell_volume = max(10, (100 - min(base_conf, 100)) * 2)
            if str(iceberg.get("type", "")).upper().startswith("SELL"):
                buy_volume, sell_volume = sell_volume, buy_volume

            iceberg_template = {
                "buy_volume": int(buy_volume),
                "sell_volume": int(sell_volume),
                "absorption_level": iceberg.get("price"),
                "bias": "Institutional Buying" if iceberg["type"] == "BUY_ABSORPTION" else "Institutional Selling"
            }

        # Gann Template
        cycle_score = float(gann.get("gann_score", 0) or 0)
        day_count = max(1, int(cycle_score * 1.5))
        next_pivot = "Near-term" if cycle_score >= 20 else "Developing"
        gann_template = {
            "day_count": day_count,
            "expansion_level": gann.get("level_100", 0),
            "next_pivot": next_pivot
        }

        # Astro Template
        harmonic = int(astro.get("harmonic", 0) or 0)
        phase = astro.get("phase") or ("Expansion" if harmonic in [2, 3, 6] else "Compression")
        window = astro.get("window") or ("08:00–10:00 UTC" if phase == "Expansion" else "13:00–15:00 UTC")
        astro_template = {
            "alignment": phase,
            "cycle_day": harmonic,
            "vol_window": window
        }

        # News Template
        news_template = news or {
            "upcoming": "USD CPI in 1h 20m",
            "expected_reaction": "High volatility spike",
            "risk_mode": "Reduced"
        }

        return {
            "context": context,
            "active_model": active_model,
            "confidence_breakdown": confidence_breakdown,
            "iceberg": iceberg_template,
            "gann": gann_template,
            "astro": astro_template,
            "news": news_template
        }
