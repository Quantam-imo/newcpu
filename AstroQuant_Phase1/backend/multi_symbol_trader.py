import time
from datetime import datetime, timezone
from engine.data_engine import DataEngine
from engine.orderflow_engine import OrderFlowEngine
from engine.iceberg_engine import IcebergEngine
from engine.fusion_engine import FusionEngine
from engine.ict_engine import ICTEngine
from engine.gann_engine import GannEngine
from engine.astro_engine import AstroEngine
from engine.regime_engine import RegimeEngine
from engine.execution_pipeline import ExecutionPipeline
from backend.modules.rollover_manager import RolloverManager
from backend.services.spread_mapper_service import SpreadMapperService
from execution.execution_manager import get_execution_manager
from execution.symbol_mapper import is_execution_supported, to_execution_symbol
from execution.config import PRIORITY_RULES, TRADE_UNIVERSE, SYMBOL_SPREAD_LIMITS
from backend.engines.news_engine import NewsEngine
from backend.services.data_freshness_service import staleness_limit_for
from execution.position_monitor import PositionMonitor


MODEL_MAX_TRADES_PER_SESSION = {
    "ICT_LIQUIDITY": 2,
    "ICEBERG": 2,
    "GANN": 1,
    "NEWS_BREAKOUT": 1,
    "EXPANSION": 2,
}

class MultiSymbolTrader:
    def __init__(self):
        self.data_engine = DataEngine()
        self.orderflow = OrderFlowEngine()
        self.iceberg_engine = IcebergEngine()
        self.fusion = FusionEngine()
        self.ict_engine = ICTEngine()
        self.gann_engine = GannEngine()
        self.astro_engine = AstroEngine()
        self.regime_engine = RegimeEngine()
        self.news_engine = NewsEngine()
        self.execution_pipeline = ExecutionPipeline()
        self.rollover_manager = RolloverManager(self.data_engine)
        self.spread_mapper = SpreadMapperService()
        self.execution_manager = get_execution_manager()
        self.trade_universe = TRADE_UNIVERSE
        self.session_trade_counter = {}
        self.active_model_by_symbol = {}
        self.running = False

    CLOSE_SCORE_DELTA_PCT = 0.08

    @staticmethod
    def _session_key():
        now_utc = datetime.now(timezone.utc)
        utc_hour = now_utc.hour
        session = "ASIA" if utc_hour < 8 else "LONDON" if utc_hour < 16 else "NY"
        return f"{now_utc.date().isoformat()}:{session}"

    def _session_trade_count(self, model_name):
        key = f"{self._session_key()}:{model_name}"
        return int(self.session_trade_counter.get(key, 0))

    def _increment_session_trade(self, model_name):
        key = f"{self._session_key()}:{model_name}"
        self.session_trade_counter[key] = self._session_trade_count(model_name) + 1

    @staticmethod
    def _safe_float(value, fallback=0.0):
        try:
            return float(value)
        except Exception:
            return float(fallback)

    @staticmethod
    def _bar_timestamp(bar):
        if not isinstance(bar, dict):
            return None

        raw_value = bar.get("time") or bar.get("ts_event") or bar.get("timestamp")
        if raw_value is None:
            return None

        if isinstance(raw_value, datetime):
            dt = raw_value
        else:
            text = str(raw_value).strip()
            if not text:
                return None
            try:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except Exception:
                return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _is_stale(self, bars, symbol):
        if not bars:
            return True

        latest = self._bar_timestamp(bars[-1])
        if latest is None:
            return True

        age_seconds = (datetime.now(timezone.utc) - latest).total_seconds()
        return age_seconds > staleness_limit_for(symbol)

    def _load_analysis_bars(self, data_symbol):
        symbol = str(data_symbol or "").upper()
        if symbol.endswith(".FUT"):
            continuous = self.rollover_manager.get_continuous_ohlcv(symbol, minutes=360)
            bars = continuous.get("bars") or []
            if bars:
                return bars

        return self.data_engine.get_ohlcv(data_symbol) or []

    def _build_model_payload(self, bars, orderflow_data, iceberg_data, ict_data, gann_data, astro_data, regime_data, news_data, fusion_data, execution_symbol):
        if not bars:
            return {}

        latest = bars[-1]
        previous = bars[-2] if len(bars) >= 2 else latest
        recent = bars[-20:] if len(bars) >= 20 else bars
        highs = [self._safe_float(bar.get("high", 0)) for bar in recent]
        lows = [self._safe_float(bar.get("low", 0)) for bar in recent]
        closes = [self._safe_float(bar.get("close", 0)) for bar in recent]
        volumes = [self._safe_float(bar.get("volume", 0)) for bar in recent]

        latest_high = self._safe_float(latest.get("high", 0))
        latest_low = self._safe_float(latest.get("low", 0))
        latest_open = self._safe_float(latest.get("open", 0))
        latest_close = self._safe_float(latest.get("close", 0))
        prev_high = self._safe_float(previous.get("high", latest_high))
        prev_low = self._safe_float(previous.get("low", latest_low))

        average_volume = (sum(volumes) / len(volumes)) if volumes else 0
        volume_spike = bool(average_volume and volumes[-1] > average_volume * 1.5)
        range_high = max(highs) if highs else latest_high
        range_low = min(lows) if lows else latest_low

        direction = str(fusion_data.get("direction", "BUY")).upper()
        if direction not in ["BUY", "SELL"]:
            direction = "BUY" if latest_close >= latest_open else "SELL"

        fvg = ict_data.get("fvg")
        fvg_price = self._safe_float((fvg or {}).get("price", latest_close))

        tr_values = []
        for index, bar in enumerate(recent):
            bar_high = self._safe_float(bar.get("high", 0))
            bar_low = self._safe_float(bar.get("low", 0))
            if index == 0:
                prev_close = self._safe_float(bar.get("open", 0))
            else:
                prev_close = self._safe_float(recent[index - 1].get("close", 0))
            tr_values.append(max(bar_high - bar_low, abs(bar_high - prev_close), abs(bar_low - prev_close)))
        atr = (sum(tr_values[-14:]) / len(tr_values[-14:])) if tr_values else max(1.0, latest_high - latest_low)

        ema_fast = (sum(closes[-9:]) / len(closes[-9:])) if closes else latest_close
        ema_slow = (sum(closes[-21:]) / len(closes[-21:])) if closes else latest_close

        swing_low = min(lows[-5:]) if lows else latest_low
        swing_high = max(highs[-5:]) if highs else latest_high
        last_hl = min(lows[-3:]) if lows else latest_low
        last_lh = max(highs[-3:]) if highs else latest_high
        midpoint = (range_high + range_low) / 2 if (range_high + range_low) else latest_close
        pullback_50 = abs(latest_close - midpoint) <= max(0.5, atr)

        high_impact_news = bool(news_data.get("trade_halt", False) or news_data.get("high_impact", False))
        spread_value = self._safe_float(SYMBOL_SPREAD_LIMITS.get(execution_symbol, 30), 30)

        payload = {
            "liquidity_sweep": bool(latest_high >= range_high or latest_low <= range_low),
            "bos": bool(ict_data.get("ict_direction")),
            "fvg": bool(fvg),
            "confidence": self._safe_float(fusion_data.get("confidence", 0), 0),
            "direction": direction,
            "price": latest_close,
            "fvg_low": min(fvg_price, latest_low),
            "fvg_high": max(fvg_price, latest_high),
            "absorption": bool(iceberg_data),
            "delta": self._safe_float(orderflow_data.get("delta", 0), 0),
            "volume_spike": volume_spike or bool(orderflow_data.get("imbalance", 0)),
            "high_impact_news": high_impact_news,
            "absorption_level": self._safe_float((iceberg_data or {}).get("price", latest_close), latest_close),
            "gann_cycle_hit": self._safe_float(gann_data.get("gann_score", 0), 0) >= 20,
            "angle_respected": bool(latest_close >= self._safe_float(gann_data.get("level_50", latest_close), latest_close) if direction == "BUY" else latest_close <= self._safe_float(gann_data.get("level_50", latest_close), latest_close)),
            "divergence": bool(astro_data.get("astro_score", 0) > 0),
            "swing_low": swing_low,
            "swing_high": swing_high,
            "range_break": bool(latest_high > prev_high or latest_low < prev_low),
            "volume_expansion": volume_spike,
            "spread": spread_value,
            "atr": atr,
            "trend_structure": bool(latest_high >= prev_high and latest_low >= prev_low) if direction == "BUY" else bool(latest_high <= prev_high and latest_low <= prev_low),
            "ema_aligned": bool(ema_fast >= ema_slow) if direction == "BUY" else bool(ema_fast <= ema_slow),
            "pullback_50": pullback_50,
            "momentum": abs(self._safe_float(orderflow_data.get("delta", 0), 0)) > 100,
            "last_hl": last_hl,
            "last_lh": last_lh,
        }

        payload["signals"] = {
            "orderflow": "BUY" if self._safe_float(orderflow_data.get("delta", 0), 0) > 0 else "SELL",
            "iceberg": "BUY" if (iceberg_data and "BUY" in str(iceberg_data.get("type", "")).upper()) else "SELL" if iceberg_data else "NEUTRAL",
            "ict": str(ict_data.get("ict_direction") or "NEUTRAL").upper(),
            "gann": "BUY" if self._safe_float(gann_data.get("gann_score", 0), 0) >= 20 else "NEUTRAL",
            "astro": "BUY" if self._safe_float(astro_data.get("astro_score", 0), 0) > 0 else "NEUTRAL",
            "regime": "BUY" if str(regime_data.get("regime", "")).upper() == "EXPANSION" and latest_close >= latest_open else "SELL" if str(regime_data.get("regime", "")).upper() == "EXPANSION" else "NEUTRAL",
        }

        return payload

    def _mark_position_exit(self, execution_symbol, reason):
        page = getattr(self.execution_manager.execution_engine, "page", None)
        if not page:
            self.execution_manager.mark_trade_closed(symbol=execution_symbol, result="EXIT_SIGNAL")
            return

        monitor = PositionMonitor(page)
        if monitor.has_open_position():
            self.execution_manager.telegram.send(
                f"⚠ Exit Signal ({reason}) detected for {execution_symbol}. Manual close/automation close handler required."
            )
            return

        self.execution_manager.mark_trade_closed(symbol=execution_symbol, result="EXIT_SIGNAL")

    def _evaluate_profile(self, profile):
        broker_symbol = profile.get("broker_symbol", "XAUUSD")
        data_symbol = profile.get("data_symbol", broker_symbol)
        priority = str(profile.get("priority", "MEDIUM")).upper()

        execution_symbol = to_execution_symbol(broker_symbol)
        if not is_execution_supported(execution_symbol):
            print(f"Skipping {broker_symbol}: unsupported execution mapping ({execution_symbol})")
            return None

        bars = self._load_analysis_bars(data_symbol)
        if not bars:
            print(f"No data for {data_symbol}")
            return None

        if self._is_stale(bars, data_symbol):
            print(f"Stale data for {data_symbol}. Auto-trade blocked.")
            return None

        of = self.orderflow.analyze(bars)
        ice = self.iceberg_engine.detect(of, bars[-1])
        ict = self.ict_engine.analyze(bars)
        gann = self.gann_engine.analyze(bars)
        astro = self.astro_engine.analyze()
        regime = self.regime_engine.detect(bars)
        news = self.news_engine.analyze(data_symbol, bars)
        fu = self.fusion.combine(of, ice, ict, gann, astro, regime)

        model_payload = self._build_model_payload(
            bars,
            of,
            ice,
            ict,
            gann,
            astro,
            regime,
            news,
            fu,
            execution_symbol,
        )

        signals = self.execution_pipeline.signal_manager.evaluate(model_payload)
        if not signals:
            return None

        rules = PRIORITY_RULES.get(priority, PRIORITY_RULES["MEDIUM"])
        min_confidence = rules["min_confidence"]

        if bool(news.get("trade_halt", False)):
            return None

        if priority == "NEWS-BASED" and not bool(news.get("high_impact", False)):
            return None

        active_direction = None
        if execution_symbol in self.execution_manager.active_symbols:
            active_direction = str(self.execution_manager.active_symbols.get(execution_symbol) or "").upper()

        ranked_signal = self.execution_pipeline.ai_engine.evaluate(signals)
        if active_direction and ranked_signal:
            ranked_side = str(ranked_signal.get("side", "")).upper()
            if ranked_side in ["BUY", "SELL"] and ranked_side != active_direction:
                self._mark_position_exit(execution_symbol, f"{ranked_signal.get('model')} reversal")
                prior_model = self.active_model_by_symbol.get(execution_symbol)
                if prior_model:
                    self.execution_pipeline.record_result(prior_model, "loss")
                self.active_model_by_symbol.pop(execution_symbol, None)
                return None

        account_balance = self.execution_manager.risk_engine.get_balance()
        start_balance = self.execution_manager.risk_engine.start_balance
        current_balance = self.execution_manager.risk_engine.current_balance
        daily_loss_abs = abs(min(0.0, self.execution_manager.risk_engine.daily_loss))
        overall_loss_abs = max(0.0, start_balance - current_balance)
        risk_per_trade_limit = float(self.execution_manager.risk_engine.prop_lock.get_rules().get("risk_per_trade", 0.003))

        account_snapshot = {
            "balance": account_balance,
            "daily_loss": daily_loss_abs,
            "daily_limit": start_balance * float(self.execution_manager.risk_engine.prop_lock.get_rules().get("daily_loss", 0.03)),
            "overall_loss": overall_loss_abs,
            "max_limit": start_balance * float(self.execution_manager.risk_engine.prop_lock.get_rules().get("max_loss", 0.08)),
            "max_per_trade": account_balance * risk_per_trade_limit,
            "open_trades": len(self.execution_manager.active_symbols),
        }

        signal = self.execution_pipeline.process_signals(signals, account_snapshot)
        if not signal:
            return None

        model_name = str(signal.get("model", ""))
        model_cap = MODEL_MAX_TRADES_PER_SESSION.get(model_name, 1)
        if self._session_trade_count(model_name) >= model_cap:
            return None

        if self._safe_float(fu.get("confidence", 0), 0) < min_confidence:
            return None

        execution_payload = {
            "direction": signal.get("side"),
            "confidence": fu.get("confidence", 0),
            "risk_percent": signal.get("risk_percent", 0.4),
            "model": signal.get("model"),
            "entry": signal.get("entry"),
            "stop": signal.get("stop"),
            "rr": signal.get("rr"),
            "ai_score": signal.get("ai_score"),
            "model_weight": signal.get("model_weight"),
            "performance_boost": signal.get("performance_boost"),
        }

        return {
            "profile": profile,
            "priority": priority,
            "broker_symbol": broker_symbol,
            "execution_symbol": execution_symbol,
            "model_name": model_name,
            "signal": signal,
            "execution_payload": execution_payload,
            "ai_score": float(signal.get("ai_score", 0) or 0),
        }

    def _execute_candidate(self, candidate, allow_concurrent=False):
        model_name = candidate.get("model_name")
        execution_symbol = candidate.get("execution_symbol")
        broker_symbol = candidate.get("broker_symbol")
        execution_payload = candidate.get("execution_payload") or {}

        executed = self.execution_manager.execute_trade(
            execution_payload,
            symbol=broker_symbol,
            allow_concurrent=allow_concurrent,
        )
        if executed:
            self._increment_session_trade(model_name)
            self.execution_manager.active_symbols[execution_symbol] = str((candidate.get("signal") or {}).get("side", "")).upper()
            self.active_model_by_symbol[execution_symbol] = model_name
        return executed

    def _apply_rollover_risk_modifier(self, signal, rollover_status):
        modified = dict(signal)
        if not rollover_status:
            modified["rollover_risk_modifier"] = 1.0
            return modified

        is_risky_rollover = bool(rollover_status.get("rollover_detected")) or bool(rollover_status.get("rollover_imminent"))
        if not is_risky_rollover:
            modified["rollover_risk_modifier"] = 1.0
            return modified

        risk = self._safe_float(modified.get("risk_percent", 0.4), 0.4)
        modified["risk_percent"] = round(risk * 0.75, 4)

        side = str(modified.get("side", "")).upper()
        entry = self._safe_float(modified.get("entry", 0), 0)
        stop = self._safe_float(modified.get("stop", entry), entry)

        if side == "BUY" and stop < entry:
            distance = entry - stop
            modified["stop"] = entry - (distance * 1.15)
        elif side == "SELL" and stop > entry:
            distance = stop - entry
            modified["stop"] = entry + (distance * 1.15)

        modified["rollover_risk_modifier"] = 0.75
        return modified

    def run(self, interval=30):
        self.running = True
        while self.running:
            candidates = []
            for profile in self.trade_universe:
                try:
                    candidate = self._evaluate_profile(profile)
                    if candidate:
                        data_symbol = str(profile.get("data_symbol", "") or "")
                        broker_symbol = str(profile.get("broker_symbol", "") or "")

                        rollover_status = None
                        if data_symbol.upper().endswith(".FUT"):
                            rollover_status = self.rollover_manager.get_rollover_status(data_symbol)

                        updated_signal = self._apply_rollover_risk_modifier(candidate.get("signal") or {}, rollover_status)

                        basis = self.spread_mapper.estimate_basis(
                            self.data_engine,
                            data_symbol,
                            broker_symbol,
                            lookback_minutes=180,
                        )
                        spread_adjusted = self.spread_mapper.apply_basis(
                            updated_signal.get("side"),
                            updated_signal.get("entry"),
                            updated_signal.get("stop"),
                            basis,
                        )

                        candidate["signal"] = updated_signal
                        candidate["execution_payload"]["risk_percent"] = updated_signal.get("risk_percent", candidate["execution_payload"].get("risk_percent", 0.4))
                        candidate["execution_payload"]["entry"] = spread_adjusted.get("entry")
                        candidate["execution_payload"]["stop"] = spread_adjusted.get("stop")
                        candidate["execution_payload"]["basis_applied"] = spread_adjusted.get("basis")
                        candidate["execution_payload"]["rollover_risk_modifier"] = updated_signal.get("rollover_risk_modifier", 1.0)
                        candidate["execution_payload"]["rollover_status"] = rollover_status or {}

                        candidates.append(candidate)
                except Exception as e:
                    print(f"Error trading {profile}: {e}")

            if candidates:
                candidates.sort(key=lambda item: float(item.get("ai_score", 0) or 0), reverse=True)
                open_trades = len(self.execution_manager.active_symbols)
                available_slots = max(0, 2 - open_trades)

                if available_slots > 0:
                    self._execute_candidate(candidates[0], allow_concurrent=False)

                if available_slots > 1 and len(candidates) > 1:
                    top_score = float(candidates[0].get("ai_score", 0) or 0)
                    second_score = float(candidates[1].get("ai_score", 0) or 0)
                    score_gap_ratio = 1.0 if top_score <= 0 else (top_score - second_score) / top_score

                    top_side = str((candidates[0].get("signal") or {}).get("side", "")).upper()
                    second_side = str((candidates[1].get("signal") or {}).get("side", "")).upper()

                    if top_side in ["BUY", "SELL"] and top_side == second_side and score_gap_ratio <= self.CLOSE_SCORE_DELTA_PCT:
                        self._execute_candidate(candidates[1], allow_concurrent=True)

            time.sleep(interval)

    def stop(self):
        self.running = False

# To start multi-symbol trading in background:
# trader = MultiSymbolTrader()
# threading.Thread(target=trader.run, daemon=True).start()
