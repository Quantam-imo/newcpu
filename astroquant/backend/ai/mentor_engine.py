from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List


class MentorEngine:

    def __init__(self):
        self.disabled_models: set[str] = set()
        self.aggressive_mode: bool = False
        self.admin_password = os.getenv("MENTOR_ADMIN_PASSWORD", "AQ-ADMIN").strip() or "AQ-ADMIN"

    def build_context(self, market_data, model_data, risk_data, phase_data):

        return {
            "market": {
                "symbol": market_data["symbol"],
                "canonical_symbol": market_data.get("canonical_symbol"),
                "pricing_source": market_data.get("pricing_source"),
                "spot_fidelity": market_data.get("spot_fidelity", {}),
                "htf_bias": market_data["htf_bias"],
                "ltf_structure": market_data["ltf_structure"],
                "session": market_data["session"],
                "volatility": market_data["volatility"],
                "news_state": market_data["news_state"],
            },
            "model": {
                "active_model": model_data["name"],
                "confidence": model_data["confidence"],
                "reason": model_data["reason"],
                "rr": model_data["rr"],
                "invalid_if": model_data["invalid_if"],
                "entry_logic": model_data.get("entry_logic", ""),
            },
            "risk": {
                "phase": phase_data["phase"],
                "risk_percent": risk_data["risk_percent"],
                "daily_buffer": risk_data["daily_buffer"],
                "static_floor": risk_data["static_floor"],
                "cooldown": risk_data["cooldown"],
            },
            "iceberg": market_data.get("iceberg", None),
            "controls": {
                "aggressive_mode": self.aggressive_mode,
                "disabled_models": sorted(list(self.disabled_models)),
            },
            "exit": model_data.get("exit", None),
            "prop_audit": phase_data.get("prop_audit", {}),
            "last_trades": phase_data.get("last_trades", []),
            "model_stats": phase_data.get("model_stats", {}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def derive_htf_bias(self, candles: List[Dict[str, Any]]) -> str:
        if len(candles) < 30:
            return "NEUTRAL"
        closes = [float(c.get("close", 0.0) or 0.0) for c in candles[-120:]]
        fast = sum(closes[-20:]) / max(1, len(closes[-20:]))
        slow = sum(closes) / max(1, len(closes))
        if fast > slow * 1.0015:
            return "BULLISH"
        if fast < slow * 0.9985:
            return "BEARISH"
        return "NEUTRAL"

    def derive_ltf_structure(self, candles: List[Dict[str, Any]]) -> str:
        if len(candles) < 20:
            return "RANGE"
        recent = candles[-20:]
        highs = [float(c.get("high", 0.0) or 0.0) for c in recent]
        lows = [float(c.get("low", 0.0) or 0.0) for c in recent]
        closes = [float(c.get("close", 0.0) or 0.0) for c in recent]

        total_range = max(highs) - min(lows)
        drift = abs(closes[-1] - closes[0])
        if total_range <= 1e-9:
            return "RANGE"

        drift_ratio = drift / total_range
        if drift_ratio >= 0.75:
            return "EXPANSION"
        if drift_ratio >= 0.35:
            return "TREND"
        return "RANGE"

    def derive_iceberg(self, candles: List[Dict[str, Any]]) -> Dict[str, Any] | None:
        if len(candles) < 10:
            return None
        recent = candles[-30:]
        strengths = []
        for c in recent:
            high = float(c.get("high", 0.0) or 0.0)
            low = float(c.get("low", 0.0) or 0.0)
            close = float(c.get("close", 0.0) or 0.0)
            open_px = float(c.get("open", 0.0) or 0.0)
            vol = float(c.get("volume", 0.0) or 0.0)
            spread = max(1e-9, high - low)
            score = vol / spread
            strengths.append((score, close, open_px))

        strongest = max(strengths, key=lambda x: x[0])
        score, price, open_px = strongest
        if score < 2500:
            return None

        bias = "BUY_PRESSURE" if price >= open_px else "SELL_PRESSURE"
        return {
            "detected": True,
            "price": round(price, 2),
            "strength": round(score / 1000.0, 2),
            "bias": bias,
            "absorption": "YES",
        }

    def infer_exit_reason(self, last_trade: Dict[str, Any], market_news_halt: bool, volatility_state: str) -> str:
        result = str(last_trade.get("result", "")).upper()
        status = str(last_trade.get("status", "")).upper()
        if market_news_halt:
            return "NEWS_HALT"
        if "INVALID" in status:
            return "MODEL_INVALIDATION"
        if volatility_state == "EXTREME":
            return "VOLATILITY_SPIKE"
        if result == "WIN":
            return "TP_HIT"
        if result == "LOSS":
            return "SL_HIT"
        return "TIME_BASED_EXIT"

    def disable_model(self, model_name: str) -> Dict[str, Any]:
        model = str(model_name or "").strip().upper()
        if not model:
            return {"status": "error", "message": "model_name required"}
        self.disabled_models.add(model)
        return {"status": "ok", "disabled_models": sorted(list(self.disabled_models))}

    def reduce_risk_mode(self) -> Dict[str, Any]:
        return {"status": "ok", "message": "Reduce risk mode acknowledged"}

    def set_aggressive_mode(self, enabled: bool, password: str) -> Dict[str, Any]:
        supplied = str(password or "").strip()
        if supplied != self.admin_password:
            return {"status": "error", "message": "invalid password"}
        self.aggressive_mode = bool(enabled)
        return {"status": "ok", "aggressive_mode": self.aggressive_mode}
