from astroquant.engine.news_engine import NewsEngine
from astroquant.engine.correlation_engine import CorrelationEngine
from astroquant.engine.model_weight_engine import ModelWeightEngine
from astroquant.engine.frequency_engine import FrequencyEngine
import datetime


def allowed_models_for_phase(phase):
    if phase == "PHASE1":
        return ["LIQUIDITY_SWEEP", "EXPANSION"]
    elif phase == "PHASE2":
        return ["LIQUIDITY_SWEEP", "EXPANSION", "ORDER_BLOCK"]
    elif phase == "FUNDED":
        return ["LIQUIDITY_SWEEP", "EXPANSION", "ORDER_BLOCK", "FVG", "ICEBERG"]
    return []


def canonical_model_name(model_name):
    aliases = {
        "ICT": "LIQUIDITY_SWEEP",
        "GANN": "ORDER_BLOCK",
        "NEWS": "FVG",
        "EXPANSION": "EXPANSION",
        "ICEBERG": "ICEBERG",
    }
    return aliases.get(model_name, model_name)


def fractional_kelly(win_rate, rr):
    if rr <= 0:
        return 0.01

    kelly = win_rate - ((1 - win_rate) / rr)
    return max(0.01, kelly * 0.25)


class Governance:

    def __init__(self, state):
        self.state = state
        self.news = NewsEngine()
        self.correlation = CorrelationEngine()
        self.weight_engine = ModelWeightEngine()
        self.freq_engine = FrequencyEngine()
        self.news.fetch_news()

    def _phase_risk_cap(self, phase):
        if phase in {"PHASE1", "PHASE2"}:
            return 1.0
        if phase == "FUNDED":
            return 2.0
        return 1.0

    def _phase_portfolio_heat_cap(self, phase):
        if phase in {"PHASE1", "PHASE2"}:
            return 2.0
        if phase == "FUNDED":
            return 3.0
        return 2.0

    def _model_win_rate(self, model):
        return self.weight_engine.win_rate(model)

    def _open_risk_percent_points(self):
        total = 0.0
        for position in self.state.open_positions.values():
            risk_value = float(position.get("risk_percent", 0.0) or 0.0)
            total += risk_value * 100
        return total

    def validate(self, signal, spread, daily_loss, phase, symbol, session="UNKNOWN"):
        if not self.news.last_fetch or (
            datetime.datetime.now(datetime.UTC) - self.news.last_fetch
        ).seconds > 600:
            self.news.fetch_news()

        mode, event = self.news.news_risk_mode(symbol)

        self.state.news_halt = (mode == "HALT")

        if mode == "HALT":
            return False, f"High impact news active: {event}"

        allowed, freq_reason = self.freq_engine.allowed_to_trade(symbol, session=session)
        if not allowed:
            return False, freq_reason

        if mode == "BREAKOUT_ONLY":
            if signal["model"] != "EXPANSION":
                return False, "Only breakout allowed after news"

        if mode == "REDUCE_RISK":
            signal["risk_modifier"] = 0.5

        base_spread_limit = 3

        if mode == "REDUCE_RISK":
            spread_limit = 2
        elif mode == "BREAKOUT_ONLY":
            spread_limit = 5
        else:
            spread_limit = base_spread_limit

        if spread > spread_limit:
            return False, "Spread too high for current volatility"

        if daily_loss > 1000 and phase == "PHASE1":
            return False, "Daily loss limit near"

        if signal["rr"] < 2:
            return False, "RR too low"

        model_name = canonical_model_name(signal.get("model", ""))
        if model_name not in allowed_models_for_phase(phase):
            return False, f"Model not allowed for {phase}"

        model_win_rate = self.weight_engine.win_rate(signal.get("model", ""))
        if model_win_rate < 0.30:
            return False, "Model temporarily disabled (cold streak)"

        correlation_heat = self.correlation.portfolio_heat(self.state.open_positions)
        if correlation_heat > 2:
            return False, "Portfolio heat too high"

        win_rate = model_win_rate
        kelly_percent_points = fractional_kelly(win_rate=win_rate, rr=float(signal.get("rr", 0.0) or 0.0)) * 100
        kelly_percent_points = min(kelly_percent_points, self._phase_risk_cap(phase))

        total_open_risk = self._open_risk_percent_points()
        max_portfolio_risk = self._phase_portfolio_heat_cap(phase)
        if total_open_risk + kelly_percent_points > max_portfolio_risk:
            return False, "Total portfolio risk exceeded"

        signal["risk_percent"] = kelly_percent_points / 100.0

        return True, "Approved"
