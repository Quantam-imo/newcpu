from engine.ai_decision_engine import AIDecisionEngine
from engine.risk_manager import RiskManager
from engine.signal_manager import SignalManager


class ExecutionPipeline:

    def __init__(self):
        self.signal_manager = SignalManager()
        self.ai_engine = AIDecisionEngine()
        self.risk_manager = RiskManager()

    def process(self, market_data, account):
        signals = self.signal_manager.evaluate(market_data)
        if not signals:
            return None

        if int(account.get("open_trades", 0) or 0) >= 2:
            return None

        if float(account.get("daily_loss", 0) or 0) >= float(account.get("daily_limit", 0) or 0):
            return None

        best_signal = self.ai_engine.evaluate(signals)
        if not best_signal:
            return None

        approved = self.risk_manager.approve(best_signal, account)
        if not approved:
            return None

        return best_signal

    def process_signals(self, signals, account):
        if not signals:
            return None

        if int(account.get("open_trades", 0) or 0) >= 2:
            return None

        if float(account.get("daily_loss", 0) or 0) >= float(account.get("daily_limit", 0) or 0):
            return None

        best_signal = self.ai_engine.evaluate(signals)
        if not best_signal:
            return None

        approved = self.risk_manager.approve(best_signal, account)
        if not approved:
            return None

        return best_signal

    def select_candidates(self, signals, account, max_candidates=2, close_score_delta_pct=0.08):
        if not signals:
            return []

        if int(account.get("open_trades", 0) or 0) >= 2:
            return []

        if float(account.get("daily_loss", 0) or 0) >= float(account.get("daily_limit", 0) or 0):
            return []

        ranked = self.ai_engine.rank(signals)
        if not ranked:
            return []

        top = ranked[0]
        if not self.risk_manager.approve(top, account):
            return []

        selected = [top]
        slots = max(0, min(int(max_candidates), 2) - int(account.get("open_trades", 0) or 0))
        if slots <= 1 or len(ranked) < 2:
            return selected[:slots]

        second = ranked[1]
        top_score = float(top.get("ai_score", 0) or 0)
        second_score = float(second.get("ai_score", 0) or 0)
        score_gap_ratio = 1.0 if top_score <= 0 else (top_score - second_score) / top_score

        same_side = str(top.get("side", "")).upper() == str(second.get("side", "")).upper()
        close_enough = score_gap_ratio <= float(close_score_delta_pct)

        if same_side and close_enough and self.risk_manager.approve(second, account):
            selected.append(second)

        return selected[:slots]

    def record_result(self, model, result):
        self.ai_engine.performance.update(model, result)
