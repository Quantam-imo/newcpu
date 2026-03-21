from astroquant.engine.model_weight_engine import ModelWeightEngine
from astroquant.engine.confidence_engine import ConfidenceEngine
from astroquant.engine.regime_engine import RegimeEngine
from astroquant.engine.performance_memory_engine import PerformanceMemory


class AIDecisionEngine:

    def __init__(self):
        self.weight_engine = ModelWeightEngine()
        self.conf_engine = ConfidenceEngine()
        self.regime_engine = RegimeEngine()
        self.memory = PerformanceMemory()

    def _normalize_confidence(self, confidence):
        value = float(confidence or 0.0)
        if value > 1.0:
            value = value / 100.0
        return max(0.0, min(1.0, value))

    def adaptive_threshold(self, drawdown, loss_streak, regime, avg_slippage, model_win_rate):
        return self.conf_engine.adjust_threshold(
            drawdown=drawdown,
            loss_streak=loss_streak,
            regime=regime,
            avg_slippage=avg_slippage,
            model_win_rate=model_win_rate,
        )

    def passes_adaptive_threshold(self, signal, adaptive_threshold):
        confidence_value = self._normalize_confidence(signal.get("confidence", 0.0))
        return confidence_value >= adaptive_threshold, confidence_value

    def rank_models(self, signals, regime_weight, session_weight, state=None, high_news=False, post_news_volatility=False, regime_context=None, symbol=None):
        ranked = []

        if regime_context:
            active_models = self.regime_engine.determine_active_models(
                volatility_regime=regime_context.get("volatility_regime", "NORMAL"),
                news_mode=regime_context.get("news_mode", "NORMAL"),
                session=regime_context.get("session", "ASIA"),
                liquidity_vacuum=bool(regime_context.get("liquidity_vacuum", False)),
                drawdown=float(regime_context.get("drawdown", 0.0) or 0.0),
            )
            signals = [s for s in signals if s.get("model") in active_models]

        for s in signals:
            model_name = s.get("model")

            if post_news_volatility and model_name != "EXPANSION":
                continue

            performance_stats = state.model_performance.get(model_name) if state else None

            if performance_stats:
                total = performance_stats["wins"] + performance_stats["losses"]
                if total > 0:
                    win_rate = performance_stats["wins"] / total
                    s["performance_weight"] = 0.8 + (win_rate * 0.4)

            if high_news and model_name == "EXPANSION":
                s["confidence"] *= 1.2
            elif high_news and model_name != "EXPANSION":
                s["confidence"] *= 0.6

            if regime_context and symbol:
                memory_score = self.memory.score(
                    model=model_name,
                    symbol=symbol,
                    session=regime_context.get("session", "ASIA"),
                    volatility=regime_context.get("volatility_regime", "NORMAL"),
                    news_mode=regime_context.get("news_mode", "NORMAL"),
                )
                s["memory_score"] = memory_score
                s["confidence"] *= (0.8 + memory_score)

            performance_weight = s.get("performance_weight", 1.0)
            model_weight = self.weight_engine.model_weight(model_name)
            score = (
                s["confidence"]
                * regime_weight
                * session_weight
                * s["rr"]
                * performance_weight
                * model_weight
            )
            s["model_weight"] = model_weight
            s["final_score"] = score
            ranked.append(s)

        ranked.sort(key=lambda x: x["final_score"], reverse=True)
        return ranked

    def select_best(self, ranked):
        if not ranked:
            return None

        if ranked[0]["final_score"] < 60:
            return None

        return ranked[0]
