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

    def build(self, delta_summary, dom_summary, iceberg_rows, time_sales_rows):
        delta = dict(delta_summary or {})
        dom = dict(dom_summary or {})
        icebergs = list(iceberg_rows or [])
        tape = list(time_sales_rows or [])

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
                35.0,
                45.0
                + (abs(delta_net) * 0.01)
                + (abs(cumulative_delta) * 0.0025)
                + (min(25.0, iceberg_strength * 2.2))
                + (min(12.0, abs(dom_imbalance) * 0.22)),
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
            "narrative": (
                f"Buy {buy_aggr:.1f}% / Sell {sell_aggr:.1f}% · "
                f"Δ {delta_net:+.0f} · CVD {cumulative_delta:+.0f} · "
                f"Imbalance {imbalance_side} · Iceberg {iceberg_count} · Absorption {absorption_bias}"
            ),
        }
