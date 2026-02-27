from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import os

from backend.engines.iceberg_engine import IcebergEngine
from backend.engines.gann_engine import GannEngine
from backend.engines.astro_engine import AstroEngine
from backend.engines.news_engine import NewsEngine
from backend.engines.cycle_engine import CycleEngine
from backend.engines.liquidity_engine import LiquidityEngine
from engine.data_engine import DataEngine
from engine.orderflow_engine import OrderFlowEngine
from backend.services.market_data_service import normalize_bars, safe_float, generate_fallback_bars


class MentorService:

    def __init__(self):
        self.iceberg = IcebergEngine()
        self.gann = GannEngine()
        self.astro = AstroEngine()
        self.news = NewsEngine()
        self.cycle = CycleEngine()
        self.liquidity = LiquidityEngine()
        self.orderflow_engine = OrderFlowEngine()
        try:
            self.data_engine = DataEngine()
        except Exception:
            self.data_engine = None
        try:
            configured_timeout = float(os.getenv("MENTOR_FETCH_TIMEOUT_SECONDS", "8"))
        except Exception:
            configured_timeout = 8.0
        self.fetch_timeout_seconds = max(2.0, min(configured_timeout, 30.0))

    def _timed_get_ohlcv(self, symbol):
        if self.data_engine is None:
            return []

        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self.data_engine.get_ohlcv, symbol)
        try:
            return future.result(timeout=self.fetch_timeout_seconds)
        except Exception:
            future.cancel()
            return []
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def _build_orderflow_snapshot(self, bars):
        if not bars:
            return {
                "buy_volume": 0,
                "sell_volume": 0,
                "low": 0,
                "high": 0,
                "delta": 0,
                "imbalance": 0,
            }

        lookback = bars[-30:]
        buy_volume = sum(bar["volume"] for bar in lookback if bar["close"] >= bar["open"])
        sell_volume = sum(bar["volume"] for bar in lookback if bar["close"] < bar["open"])
        low = min(bar["low"] for bar in lookback)
        high = max(bar["high"] for bar in lookback)

        of = self.orderflow_engine.analyze(lookback)

        return {
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "low": low,
            "high": high,
            "delta": safe_float(of.get("delta", 0)),
            "imbalance": int(of.get("imbalance", 0)),
        }

    @staticmethod
    def _build_context(bars, orderflow, liquidity_data, cycle_data):
        if len(bars) < 5:
            return {
                "htf_bias": "Neutral",
                "ltf_structure": "Undetermined",
                "liquidity": "Balanced",
                "kill_zone": "Monitoring",
            }

        closes = [bar["close"] for bar in bars[-20:]]
        short_avg = sum(closes[-5:]) / 5
        long_avg = sum(closes) / len(closes)
        htf_bias = "Bullish" if short_avg >= long_avg else "Bearish"

        ltf_structure = "Higher Low" if bars[-1]["close"] >= bars[-2]["close"] else "Lower High"
        liquidity = "Buy-side" if orderflow["buy_volume"] >= orderflow["sell_volume"] else "Sell-side"

        hour = datetime.now(timezone.utc).hour
        if 6 <= hour < 10:
            kill_zone = "London Active"
        elif 13 <= hour < 17:
            kill_zone = "New York Active"
        else:
            kill_zone = "Off Session"

        return {
            "htf_bias": htf_bias,
            "ltf_structure": ltf_structure,
            "liquidity": f"{liquidity} ({liquidity_data.get('bias', 'Neutral')})",
            "kill_zone": kill_zone,
            "cycle_phase": cycle_data.get("phase", "Build-up"),
        }

    @staticmethod
    def _build_confidence_breakdown(orderflow, gann_data, astro_data, news_data, cycle_data, liquidity_data):
        delta_magnitude = abs(orderflow.get("delta", 0))
        flow_score = min(24, int(delta_magnitude / 20))

        imbalance_score = 16 if orderflow.get("imbalance", 0) else 8
        gann_score = 14 if gann_data.get("square_level") == "45°" else 10
        astro_score = 14 if astro_data.get("volatility_bias") == "High" else 9
        news_score = 6 if news_data.get("trade_halt") else 14
        cycle_score = 14 if cycle_data.get("is_cycle") else 9
        liquidity_score = 13 if liquidity_data.get("bias") in ["Buy-side", "Sell-side"] else 8

        return {
            "OrderFlow": flow_score,
            "Iceberg": imbalance_score,
            "Gann": gann_score,
            "Astro": astro_score,
            "Cycle": cycle_score,
            "Liquidity": liquidity_score,
            "News": news_score,
        }

    @staticmethod
    def _build_governance(news_data, orderflow):
        trade_halt = bool(news_data.get("trade_halt"))
        elevated_imbalance = int(orderflow.get("imbalance", 0)) == 1
        defensive_mode = trade_halt or elevated_imbalance

        return {
            "mode": "Defensive" if defensive_mode else "Stable",
            "loss_streak": 1 if defensive_mode else 0,
            "spread_filter": True,
            "slippage_monitor": "Heightened" if defensive_mode else "Active",
        }

    def build(self, symbol):
        raw_bars = self._timed_get_ohlcv(symbol)
        price_data = normalize_bars(raw_bars) if raw_bars else generate_fallback_bars(120)
        orderflow = self._build_orderflow_snapshot(price_data)

        iceberg_data = self.iceberg.analyze(symbol, orderflow)
        gann_data = self.gann.analyze(symbol, price_data)
        astro_data = self.astro.analyze(symbol)
        cycle_data = self.cycle.analyze(price_data)
        liquidity_data = self.liquidity.analyze(price_data)
        news_data = self.news.analyze(symbol, price_data)
        governance = self._build_governance(news_data, orderflow)
        context = self._build_context(price_data, orderflow, liquidity_data, cycle_data)

        breakdown = self._build_confidence_breakdown(orderflow, gann_data, astro_data, news_data, cycle_data, liquidity_data)
        confidence = max(1, min(99, sum(breakdown.values())))

        defensive_mode = governance["mode"] == "Defensive"
        risk_mode = "Defensive" if defensive_mode else "Normal"

        narrative = (
            f"{context['htf_bias']} bias with {context['liquidity']} liquidity; "
            f"iceberg pressure {iceberg_data['pressure'].lower()} near {iceberg_data['zone']}. "
            f"News state: {news_data['high_impact']}"
        )

        return {
            "symbol": symbol,
            "active_model": "Fusion Model 3",
            "confidence": confidence,
            "risk_mode": risk_mode,
            "defensive_mode": defensive_mode,
            "institutional_narrative": narrative,
            "confidence_breakdown": breakdown,
            "context": context,
            "iceberg": iceberg_data,
            "gann": gann_data,
            "astro": astro_data,
            "cycle": cycle_data,
            "liquidity": liquidity_data,
            "news": news_data,
            "governance": governance,
        }
