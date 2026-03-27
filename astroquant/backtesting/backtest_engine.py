"""
Backtesting Engine for AstroQuant - Multi-Model Comparison

Supports:
- ICT Engine (Structure, Liquidity, FVG, Order Blocks)
- GANN Engine (Square-9, Spiral, Price-Time)
- Astrology Engine (Harmonic windows, aspects)
- Mentor (Orchestrated AI signal)

Calculates metrics:
- Win Rate
- Profit Factor
- Sharpe Ratio
- Max Drawdown
- Consecutive Wins/Losses
- Recovery Factor
"""

from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import math
import json
from datetime import datetime

class TradeSignal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"

@dataclass
class Trade:
    """Represents a single backtest trade"""
    signal_source: str  # ICT, GANN, ASTRO, MENTOR
    entry_price: float
    entry_time: int  # candle index
    exit_price: Optional[float] = None
    exit_time: Optional[int] = None
    direction: str = "BUY"  # BUY or SELL
    profit_loss: float = 0.0
    pips: float = 0.0
    confidence: float = 0.5
    
    def to_dict(self):
        return asdict(self)

@dataclass
class BacktestMetrics:
    """Backtesting performance metrics"""
    signal_source: str
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_profit: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    recovery_factor: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    risk_reward_ratio: float = 0.0
    
    def to_dict(self):
        return asdict(self)

class BacktestEngine:
    """Main backtesting engine for multi-model comparison"""
    
    def __init__(self, starting_balance: float = 50000, risk_percent: float = 1.0):
        self.starting_balance = starting_balance
        self.current_balance = starting_balance
        self.risk_percent = risk_percent
        self.trades: Dict[str, List[Trade]] = {}
        self.equity_curve: Dict[str, List[float]] = {}
        self.metrics: Dict[str, BacktestMetrics] = {}
        
    def add_trade(self, signal_source: str, trade: Trade):
        """Add a trade to the backtest"""
        if signal_source not in self.trades:
            self.trades[signal_source] = []
        self.trades[signal_source].append(trade)
    
    def calculate_metrics(self, signal_source: str) -> BacktestMetrics:
        """Calculate all metrics for a signal source"""
        if signal_source not in self.trades:
            return BacktestMetrics(signal_source=signal_source)
        
        trades = self.trades[signal_source]
        if not trades:
            return BacktestMetrics(signal_source=signal_source)
        
        metrics = BacktestMetrics(signal_source=signal_source)
        
        # Filter closed trades
        closed_trades = [t for t in trades if t.exit_price is not None]
        metrics.total_trades = len(closed_trades)
        
        if not closed_trades:
            return metrics
        
        # Calculate P&L for each trade
        pls = []
        wins = []
        losses = []
        consecutive_wins = 0
        consecutive_losses = 0
        
        for trade in closed_trades:
            if trade.direction == "BUY":
                pnl = (trade.exit_price - trade.entry_price) * 100  # in pips (0.01 per pip)
            else:  # SELL
                pnl = (trade.entry_price - trade.exit_price) * 100
            
            pls.append(pnl)
            trade.pips = pnl
            
            if pnl > 0:
                metrics.winning_trades += 1
                wins.append(pnl)
                consecutive_wins += 1
                consecutive_losses = 0
                metrics.max_consecutive_wins = max(metrics.max_consecutive_wins, consecutive_wins)
            else:
                metrics.losing_trades += 1
                losses.append(abs(pnl))
                consecutive_losses += 1
                consecutive_wins = 0
                metrics.max_consecutive_losses = max(metrics.max_consecutive_losses, consecutive_losses)
            
            metrics.gross_profit += max(0, pnl)
            metrics.gross_loss += max(0, -pnl)
        
        # Calculate derived metrics
        metrics.net_profit = metrics.gross_profit - metrics.gross_loss
        metrics.win_rate = metrics.winning_trades / metrics.total_trades if metrics.total_trades > 0 else 0.0
        
        if metrics.gross_loss > 0:
            metrics.profit_factor = metrics.gross_profit / metrics.gross_loss
        else:
            metrics.profit_factor = float('inf') if metrics.gross_profit > 0 else 0.0
        
        if wins:
            metrics.avg_win = sum(wins) / len(wins)
        if losses:
            metrics.avg_loss = sum(losses) / len(losses)
        
        if metrics.avg_loss > 0:
            metrics.risk_reward_ratio = metrics.avg_win / metrics.avg_loss
        
        # Sharpe Ratio (simplified - using std dev of returns)
        if len(pls) > 1:
            mean_pl = sum(pls) / len(pls)
            variance = sum((x - mean_pl) ** 2 for x in pls) / len(pls)
            std_dev = math.sqrt(variance) if variance > 0 else 0.0001
            metrics.sharpe_ratio = (mean_pl / std_dev) * math.sqrt(252)  # Annualized
        
        # Max Drawdown
        equity = self.starting_balance
        peak_equity = equity
        max_dd = 0.0
        
        for trade in closed_trades:
            equity += trade.pips
            if equity < peak_equity:
                dd = (peak_equity - equity) / peak_equity
                max_dd = max(max_dd, dd)
            else:
                peak_equity = equity
        
        metrics.max_drawdown = max_dd
        
        # Recovery Factor
        if metrics.max_drawdown > 0:
            max_dd_in_pips = metrics.max_drawdown * self.starting_balance / 100
            metrics.recovery_factor = metrics.net_profit / max_dd_in_pips if max_dd_in_pips > 0 else 0.0
        
        self.metrics[signal_source] = metrics
        return metrics
    
    def calculate_all_metrics(self) -> Dict[str, BacktestMetrics]:
        """Calculate metrics for all signal sources"""
        for signal_source in self.trades.keys():
            self.calculate_metrics(signal_source)
        return self.metrics
    
    def get_equity_curve(self, signal_source: str) -> List[float]:
        """Get equity curve for a signal source"""
        if signal_source not in self.trades:
            return []
        
        trades = self.trades[signal_source]
        equity_curve = [self.starting_balance]
        
        for trade in trades:
            if trade.exit_price is not None:
                equity = equity_curve[-1] + trade.pips
                equity_curve.append(equity)
        
        self.equity_curve[signal_source] = equity_curve
        return equity_curve
    
    def compare_models(self) -> Dict:
        """Generate comparison report for all models"""
        self.calculate_all_metrics()
        
        comparison = {
            "backtest_date": datetime.now().isoformat(),
            "starting_balance": self.starting_balance,
            "models": {}
        }
        
        for signal_source, metrics in self.metrics.items():
            equity_curve = self.get_equity_curve(signal_source)
            final_balance = equity_curve[-1] if equity_curve else self.starting_balance
            
            comparison["models"][signal_source] = {
                "metrics": metrics.to_dict(),
                "final_balance": final_balance,
                "return_percent": ((final_balance - self.starting_balance) / self.starting_balance) * 100,
                "equity_curve": equity_curve,
                "trades": [t.to_dict() for t in self.trades.get(signal_source, [])]
            }
        
        # Rank models by net profit
        ranked_models = sorted(
            comparison["models"].items(),
            key=lambda x: x[1]["metrics"]["net_profit"],
            reverse=True
        )
        
        comparison["ranking"] = [
            {
                "rank": i + 1,
                "model": model_name,
                "net_profit": data["metrics"]["net_profit"],
                "win_rate": f"{data['metrics']['win_rate']*100:.1f}%",
                "sharpe_ratio": f"{data['metrics']['sharpe_ratio']:.2f}",
                "max_drawdown": f"{data['metrics']['max_drawdown']*100:.1f}%"
            }
            for i, (model_name, data) in enumerate(ranked_models)
        ]
        
        return comparison
    
    def export_report(self, filepath: str):
        """Export backtest report to JSON"""
        report = self.compare_models()
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
        return filepath


# Example usage
if __name__ == "__main__":
    engine = BacktestEngine(starting_balance=50000, risk_percent=1.0)
    
    # Simulate ICT trades
    engine.add_trade("ICT", Trade(
        signal_source="ICT",
        entry_price=2050.0,
        entry_time=10,
        exit_price=2055.0,
        exit_time=15,
        direction="BUY",
        confidence=0.85
    ))
    
    engine.add_trade("ICT", Trade(
        signal_source="ICT",
        entry_price=2055.0,
        entry_time=20,
        exit_price=2050.0,
        exit_time=25,
        direction="BUY",
        confidence=0.60
    ))
    
    # Simulate GANN trades
    engine.add_trade("GANN", Trade(
        signal_source="GANN",
        entry_price=2050.0,
        entry_time=10,
        exit_price=2058.0,
        exit_time=18,
        direction="BUY",
        confidence=0.75
    ))
    
    # Generate comparison
    report = engine.compare_models()
    
    print("\n" + "="*80)
    print("BACKTESTING REPORT")
    print("="*80)
    
    for rank_item in report["ranking"]:
        print(f"\n#{rank_item['rank']} - {rank_item['model']}")
        print(f"   Net Profit: {rank_item['net_profit']:.2f} pips")
        print(f"   Win Rate: {rank_item['win_rate']}")
        print(f"   Sharpe Ratio: {rank_item['sharpe_ratio']}")
        print(f"   Max Drawdown: {rank_item['max_drawdown']}")
