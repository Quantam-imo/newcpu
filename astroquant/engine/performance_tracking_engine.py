from __future__ import annotations

from datetime import datetime, timezone


class PerformanceTrackingEngine:
    def __init__(self):
        self.trades = []

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    def record_trade(self, symbol, model, pnl, result, meta=None):
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": str(symbol or "UNKNOWN").upper(),
            "model": str(model or "UNKNOWN"),
            "pnl": self._to_float(pnl, 0.0),
            "result": str(result or "UNKNOWN").upper(),
            "meta": dict(meta or {}),
        }
        self.trades.append(entry)
        return entry

    def summary(self):
        total = len(self.trades)
        if total == 0:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "net_pnl": 0.0,
                "avg_pnl": 0.0,
                "profit_factor": 0.0,
            }

        wins = 0
        losses = 0
        gross_profit = 0.0
        gross_loss = 0.0
        net_pnl = 0.0

        for trade in self.trades:
            pnl = self._to_float(trade.get("pnl"), 0.0)
            net_pnl += pnl
            if pnl > 0:
                wins += 1
                gross_profit += pnl
            elif pnl < 0:
                losses += 1
                gross_loss += abs(pnl)

        win_rate = (wins / total) * 100.0
        avg_pnl = net_pnl / total
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

        return {
            "total_trades": int(total),
            "wins": int(wins),
            "losses": int(losses),
            "win_rate": round(win_rate, 2),
            "net_pnl": round(net_pnl, 2),
            "avg_pnl": round(avg_pnl, 2),
            "profit_factor": round(profit_factor, 3),
        }
