import json
from datetime import datetime, timezone
from pathlib import Path


JOURNAL_PATH = Path(__file__).resolve().parents[1] / "data" / "mentor_journal"
JOURNAL_PATH.mkdir(parents=True, exist_ok=True)


class AIMentor:

    def generate(self, market_data, signal_data):
        price = market_data.get("price")
        symbol = market_data.get("symbol")
        confidence = int(signal_data.get("confidence", 0) or 0)

        prices = self.price_template(market_data)
        iceberg = self.iceberg_analysis(signal_data)
        recommended_side = self.recommended_side(signal_data, iceberg)

        response = {
            "symbol": symbol,
            "price": price,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prices": prices,
            "context": self.market_context(market_data),
            "ict": self.ict_analysis(signal_data),
            "iceberg": iceberg,
            "gann": self.gann_analysis(signal_data),
            "astro": self.astro_analysis(signal_data),
            "news": self.news_analysis(signal_data),
            "risk": self.risk_explanation(signal_data),
            "confidence": confidence,
            "recommended_side": recommended_side,
            "institutional_reasoning": self.institutional_reasoning(signal_data),
            "trade_justification": self.trade_justification(signal_data, recommended_side),
            "verdict": self.final_verdict(signal_data),
        }

        self.save_journal(response)
        return response

    def market_context(self, data):
        return {
            "htf_bias": data.get("htf_bias", "Neutral"),
            "ltf_structure": data.get("ltf_structure", "Ranging"),
            "liquidity_zones": data.get("liquidity", []),
            "kill_zone": data.get("kill_zone", "Monitoring"),
        }

    def ict_analysis(self, data):
        return {
            "fvg_detected": data.get("fvg", False),
            "order_block": data.get("order_block"),
            "breaker": data.get("breaker"),
            "structure_shift": data.get("bos"),
        }

    def price_template(self, data):
        return {
            "current_price": data.get("price"),
            "equilibrium": data.get("equilibrium"),
            "range_low": data.get("range_low"),
            "range_high": data.get("range_high"),
            "execution_zone": data.get("execution_zone", data.get("zone", "N/A")),
        }

    def iceberg_analysis(self, data):
        buy_pressure = int(data.get("buy_volume", 0) or 0)
        sell_pressure = int(data.get("sell_volume", 0) or 0)

        if buy_pressure > sell_pressure:
            dominant_pressure = "Buying"
        elif sell_pressure > buy_pressure:
            dominant_pressure = "Selling"
        else:
            dominant_pressure = "Balanced"

        return {
            "absorption_detected": data.get("absorption", False),
            "buy_volume": buy_pressure,
            "sell_volume": sell_pressure,
            "institutional_side": data.get("institutional_side", "Unknown"),
            "pressure": data.get("pressure", "Balanced"),
            "zone": data.get("zone", "N/A"),
            "institutional_buying_pressure": buy_pressure,
            "institutional_selling_pressure": sell_pressure,
            "net_pressure": buy_pressure - sell_pressure,
            "dominant_pressure": dominant_pressure,
        }

    def gann_analysis(self, data):
        return {
            "day_count": data.get("gann_day_count"),
            "bar_count": data.get("gann_bar_count"),
            "angle_alignment": data.get("gann_angle"),
            "square_level": data.get("gann_square"),
        }

    def astro_analysis(self, data):
        return {
            "cycle_active": data.get("astro_cycle"),
            "planetary_alignment": data.get("astro_alignment"),
            "phase": data.get("astro_phase"),
            "window": data.get("astro_window"),
        }

    def news_analysis(self, data):
        return {
            "news_bias": data.get("news_bias", "Neutral"),
            "volatility_expected": data.get("volatility", "Normal"),
            "trade_halt": bool(data.get("trade_halt", False)),
            "high_impact": data.get("high_impact", "None"),
        }

    def risk_explanation(self, data):
        return {
            "risk_percent": data.get("risk", 0),
            "rr_ratio": data.get("rr", "1:2"),
            "max_loss_today": data.get("daily_limit"),
            "risk_mode": data.get("risk_mode", "Normal"),
        }

    def institutional_reasoning(self, data):
        htf_bias = data.get("htf_bias", "Neutral")
        ltf_structure = data.get("ltf_structure", "Ranging")
        side = data.get("institutional_side", "Unknown")
        news_bias = data.get("news_bias", "Neutral")
        return (
            f"HTF bias {htf_bias} with LTF structure {ltf_structure}. "
            f"Orderflow indicates institutional {side.lower()} pressure while news bias is {news_bias.lower()}."
        )

    def trade_justification(self, data, recommended_side):
        confidence = int(data.get("confidence", 0) or 0)
        rr = data.get("rr", "1:2")
        risk = data.get("risk", 0)
        return (
            f"Setup qualifies at {confidence}% confidence with risk {risk}% and target RR {rr}. "
            f"Preferred side is {recommended_side}. Execution allowed only if volatility regime remains compliant."
        )

    def recommended_side(self, data, iceberg):
        if bool(data.get("trade_halt", False)):
            return "WAIT"

        confidence = int(data.get("confidence", 0) or 0)
        buy_pressure = int(iceberg.get("institutional_buying_pressure", 0) or 0)
        sell_pressure = int(iceberg.get("institutional_selling_pressure", 0) or 0)

        pressure_gap = abs(buy_pressure - sell_pressure)
        if confidence < 60 or pressure_gap < 3:
            return "WAIT"

        return "BUY" if buy_pressure > sell_pressure else "SELL"

    def final_verdict(self, data):
        confidence = int(data.get("confidence", 0) or 0)

        if confidence > 80:
            return "High Probability Institutional Setup"
        if confidence > 60:
            return "Moderate Setup – Managed Risk"
        return "Low Confidence – Standby"

    def save_journal(self, data):
        filename = f"{datetime.now(timezone.utc):%Y-%m-%d}.json"
        path = JOURNAL_PATH / filename

        existing = []
        if path.exists():
            try:
                with path.open("r", encoding="utf-8") as file:
                    loaded = json.load(file)
                    if isinstance(loaded, list):
                        existing = loaded
            except (json.JSONDecodeError, OSError):
                existing = []

        existing.append(data)

        with path.open("w", encoding="utf-8") as file:
            json.dump(existing, file, indent=4)
