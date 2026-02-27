import copy
import datetime
import os


class BrokerAdaptationEngine:

    def __init__(self):
        self.max_divergence_pct = float(os.getenv("BROKER_MAX_DIVERGENCE_PCT", "0.20"))
        self.max_daily_drawdown_pct = float(os.getenv("BROKER_MAX_DAILY_DRAWDOWN_PCT", "3.0"))
        self.max_slippage = float(os.getenv("BROKER_MAX_SLIPPAGE", "2.0"))
        self._symbols = {}

    @staticmethod
    def _utc_now_iso():
        return datetime.datetime.now(datetime.timezone.utc).isoformat()

    @staticmethod
    def _safe_float(value):
        try:
            return float(value)
        except Exception:
            return None

    def _state_for(self, symbol):
        key = str(symbol or "").upper()
        state = self._symbols.get(key)
        if state is None:
            state = {
                "symbol": key,
                "avg_spread": None,
                "avg_slippage": None,
                "samples": 0,
                "last_decision": "INIT",
                "last_reason": "--",
                "last_update": self._utc_now_iso(),
            }
            self._symbols[key] = state
        return state

    @staticmethod
    def _ema(previous, current, alpha=0.25):
        if previous is None:
            return current
        return (alpha * current) + ((1.0 - alpha) * previous)

    def assess(self, symbol, signal, broker_feed, max_spread):
        state = self._state_for(symbol)
        feed_price = (broker_feed or {}).get("price", {})
        feed_account = (broker_feed or {}).get("account", {})

        bid = self._safe_float(feed_price.get("bid"))
        ask = self._safe_float(feed_price.get("ask"))
        if bid is None or ask is None:
            state["last_decision"] = "BLOCK"
            state["last_reason"] = "Broker quote unavailable"
            state["last_update"] = self._utc_now_iso()
            return False, state["last_reason"], {}

        spread = max(0.0, ask - bid)
        state["avg_spread"] = self._ema(state.get("avg_spread"), spread)

        max_allowed_spread = self._safe_float(max_spread)
        if max_allowed_spread is not None and spread > max_allowed_spread:
            state["last_decision"] = "BLOCK"
            state["last_reason"] = f"Spread anomaly ({spread:.3f} > {max_allowed_spread:.3f})"
            state["last_update"] = self._utc_now_iso()
            return False, state["last_reason"], {}

        balance = self._safe_float(feed_account.get("balance"))
        equity = self._safe_float(feed_account.get("equity"))
        if balance and equity is not None and balance > 0:
            drawdown_pct = max(0.0, ((balance - equity) / balance) * 100.0)
            if drawdown_pct > self.max_daily_drawdown_pct:
                state["last_decision"] = "BLOCK"
                state["last_reason"] = f"Account drawdown high ({drawdown_pct:.2f}%)"
                state["last_update"] = self._utc_now_iso()
                return False, state["last_reason"], {}

        side = str((signal or {}).get("direction") or (signal or {}).get("side") or "").upper()
        execution_price = ask if side == "BUY" else bid if side == "SELL" else (ask + bid) / 2.0

        intended_entry = self._safe_float((signal or {}).get("entry"))
        if intended_entry is not None and execution_price is not None and execution_price > 0:
            divergence_pct = abs(intended_entry - execution_price) / execution_price * 100.0
            if divergence_pct > self.max_divergence_pct:
                state["last_decision"] = "BLOCK"
                state["last_reason"] = f"Divergence high ({divergence_pct:.3f}%)"
                state["last_update"] = self._utc_now_iso()
                return False, state["last_reason"], {}
        else:
            divergence_pct = 0.0

        state["samples"] = int(state.get("samples", 0)) + 1
        state["last_decision"] = "ALLOW"
        state["last_reason"] = "OK"
        state["last_update"] = self._utc_now_iso()

        adapted = {
            "execution_price": execution_price,
            "broker_spread": spread,
            "divergence_pct": round(divergence_pct, 5),
        }
        return True, "OK", adapted

    def register_fill(self, symbol, intended_price, actual_price):
        state = self._state_for(symbol)
        intended = self._safe_float(intended_price)
        actual = self._safe_float(actual_price)
        if intended is None or actual is None:
            return

        slippage = abs(actual - intended)
        state["avg_slippage"] = self._ema(state.get("avg_slippage"), slippage)
        state["last_update"] = self._utc_now_iso()

    def get_state(self):
        return {
            "limits": {
                "max_divergence_pct": self.max_divergence_pct,
                "max_daily_drawdown_pct": self.max_daily_drawdown_pct,
                "max_slippage": self.max_slippage,
            },
            "symbols": copy.deepcopy(self._symbols),
            "updated_at": self._utc_now_iso(),
        }
