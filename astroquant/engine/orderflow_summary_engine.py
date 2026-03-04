from __future__ import annotations


class OrderflowSummaryEngine:
    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    @staticmethod
    def _to_int(value, default=0):
        try:
            return int(float(value))
        except Exception:
            return int(default)

    def _regime_profile(self, regime_mode: str, volatility_mode: str):
        mode = str(regime_mode or "STANDARD").upper()
        vol = str(volatility_mode or "NORMAL").upper()

        base = {
            "name": mode,
            "delta_scale": 0.010,
            "cvd_scale": 0.0025,
            "dom_scale": 0.22,
            "iceberg_scale": 2.20,
            "min_confidence": 35.0,
            "base_confidence": 45.0,
            "alert_delta": 180.0,
            "alert_cvd": 420.0,
            "alert_dom_imb": 11.0,
            "alert_icebergs": 2,
        }

        if mode in {"STRICT", "CONSERVATIVE"}:
            base.update(
                {
                    "name": "STRICT",
                    "delta_scale": 0.0085,
                    "cvd_scale": 0.0021,
                    "dom_scale": 0.18,
                    "iceberg_scale": 1.90,
                    "min_confidence": 40.0,
                    "base_confidence": 43.0,
                    "alert_delta": 240.0,
                    "alert_cvd": 600.0,
                    "alert_dom_imb": 14.0,
                    "alert_icebergs": 3,
                }
            )
        elif mode in {"AGGRESSIVE", "HIGH_BETA"}:
            base.update(
                {
                    "name": "AGGRESSIVE",
                    "delta_scale": 0.013,
                    "cvd_scale": 0.0032,
                    "dom_scale": 0.28,
                    "iceberg_scale": 2.60,
                    "min_confidence": 32.0,
                    "base_confidence": 47.0,
                    "alert_delta": 120.0,
                    "alert_cvd": 280.0,
                    "alert_dom_imb": 8.0,
                    "alert_icebergs": 1,
                }
            )

        if vol in {"HIGH", "EXTREME"}:
            base["alert_delta"] *= 1.15
            base["alert_cvd"] *= 1.20
            base["alert_dom_imb"] *= 1.08

        return base

    def build(self, delta_summary, dom_summary, iceberg_rows, time_sales_rows, regime_mode="STANDARD", volatility_mode="NORMAL"):
        delta = dict(delta_summary or {})
        dom = dict(dom_summary or {})
        icebergs = list(iceberg_rows or [])
        tape = list(time_sales_rows or [])
        profile = self._regime_profile(regime_mode=regime_mode, volatility_mode=volatility_mode)

        buy_aggr = self._to_float(delta.get("buy_aggression"), 0.0)
        sell_aggr = self._to_float(delta.get("sell_aggression"), 0.0)
        if buy_aggr == 0.0 and sell_aggr == 0.0 and tape:
            buy_sz = 0.0
            sell_sz = 0.0
            for row in tape:
                size = max(0.0, self._to_float(row.get("size"), 0.0))
                side = str(row.get("side", "")).upper()
                if side == "BUY":
                    buy_sz += size
                elif side == "SELL":
                    sell_sz += size
            total = max(1.0, buy_sz + sell_sz)
            buy_aggr = (buy_sz / total) * 100.0
            sell_aggr = (sell_sz / total) * 100.0

        delta_net = self._to_float(delta.get("delta"), 0.0)
        cumulative_delta = self._to_float(delta.get("cumulative_delta"), 0.0)
        imbalance_side = str(delta.get("imbalance") or dom.get("imbalance_side") or "NEUTRAL").upper()

        iceberg_count = len(icebergs)
        iceberg_strength = sum(max(0.0, self._to_float(row.get("absorption_strength"), 0.0)) for row in icebergs)
        absorption_bias = "NEUTRAL"
        if iceberg_count > 0:
            if delta_net > 0:
                absorption_bias = "BULLISH"
            elif delta_net < 0:
                absorption_bias = "BEARISH"

        spread = self._to_float(dom.get("spread"), 0.0)
        dom_imbalance = self._to_float(dom.get("imbalance"), 0.0)

        confidence = min(
            99.0,
            max(
                float(profile["min_confidence"]),
                float(profile["base_confidence"])
                + (abs(delta_net) * float(profile["delta_scale"]))
                + (abs(cumulative_delta) * float(profile["cvd_scale"]))
                + (min(25.0, iceberg_strength * float(profile["iceberg_scale"])))
                + (min(12.0, abs(dom_imbalance) * float(profile["dom_scale"]))),
            ),
        )

        strong_delta = abs(delta_net) >= float(profile["alert_delta"])
        strong_cvd = abs(cumulative_delta) >= float(profile["alert_cvd"])
        strong_dom = abs(dom_imbalance) >= float(profile["alert_dom_imb"])
        strong_iceberg = iceberg_count >= int(profile["alert_icebergs"])

        trigger_count = int(strong_delta) + int(strong_cvd) + int(strong_dom) + int(strong_iceberg)
        if trigger_count >= 3:
            alert_level = "HIGH"
        elif trigger_count == 2:
            alert_level = "MEDIUM"
        else:
            alert_level = "LOW"

        signal_strength = min(
            100.0,
            max(
                0.0,
                (abs(delta_net) / max(1.0, float(profile["alert_delta"]))) * 30.0
                + (abs(cumulative_delta) / max(1.0, float(profile["alert_cvd"]))) * 30.0
                + (abs(dom_imbalance) / max(1.0, float(profile["alert_dom_imb"]))) * 20.0
                + (min(1.0, iceberg_count / max(1.0, float(profile["alert_icebergs"])))) * 20.0,
            ),
        )

        return {
            "buy_aggression": round(buy_aggr, 2),
            "sell_aggression": round(sell_aggr, 2),
            "delta": round(delta_net, 2),
            "cumulative_delta": round(cumulative_delta, 2),
            "imbalance": imbalance_side,
            "dom_spread": round(spread, 5),
            "dom_imbalance": round(dom_imbalance, 2),
            "iceberg_count": int(iceberg_count),
            "iceberg_strength": round(iceberg_strength, 2),
            "absorption": absorption_bias,
            "confidence": round(confidence, 2),
            "alert_level": alert_level,
            "signal_strength": round(signal_strength, 2),
            "regime_mode": str(profile.get("name", "STANDARD")),
            "thresholds": {
                "delta": round(float(profile["alert_delta"]), 2),
                "cumulative_delta": round(float(profile["alert_cvd"]), 2),
                "dom_imbalance": round(float(profile["alert_dom_imb"]), 2),
                "icebergs": int(profile["alert_icebergs"]),
            },
            "narrative": (
                f"Buy {buy_aggr:.1f}% / Sell {sell_aggr:.1f}% · "
                f"Δ {delta_net:+.0f} · CVD {cumulative_delta:+.0f} · "
                f"Imbalance {imbalance_side} · Iceberg {iceberg_count} · Absorption {absorption_bias} · "
                f"Alert {alert_level} ({str(profile.get('name', 'STANDARD'))})"
            ),
        }
