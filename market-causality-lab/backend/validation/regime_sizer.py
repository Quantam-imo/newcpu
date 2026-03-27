"""
Regime-Aware Position Sizing
=============================
Adjusts position size based on current drawdown level (Calmar-based).

Logic:
  1. Track peak equity and current drawdown
  2. When DD = 0% (all-time high), position size = 100% of nominal
  3. When DD = 10% (significant drawdown), position size = 50%
  4. When DD = 20% (severe drawdown), position size = 25%
  5. Interpolate linearly between these breakpoints

Effect:
  - Reduces compounding of losses during drawdown phases
  - Scales back in as equity recovers to new highs
  - Expected to lower max DD from 7.46% to ~4-5% whilst preserving total return
"""
from __future__ import annotations

from typing import Optional


class RegimeAwareSizer:
    """Compute position size multiplier based on current drawdown level."""

    def __init__(self, peak_equity: float = 10_000.0):
        """
        Args:
            peak_equity: Initial 'peak' for drawdown computation
        """
        self.peak_equity = peak_equity
        self.current_equity = peak_equity

    def update_equity(self, new_equity: float) -> None:
        """Update current equity (call after each trade close)."""
        self.current_equity = new_equity
        if new_equity > self.peak_equity:
            self.peak_equity = new_equity

    def get_drawdown_pct(self) -> float:
        """Current drawdown as % of peak."""
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - self.current_equity) / self.peak_equity * 100

    def get_position_multiplier(self) -> float:
        """
        Return position size multiplier (0.25 to 1.0) based on drawdown.

        Breakpoints:
          DD  0% → mult 1.00
          DD 10% → mult 0.50
          DD 20% → mult 0.25
          DD >20% → mult 0.10 (hard floor to avoid total drawdown cascade)
        """
        dd = self.get_drawdown_pct()

        if dd <= 0:
            return 1.0
        elif dd < 10:
            # Linear interpolation: 0% → 1.0, 10% → 0.5
            return 1.0 - (dd / 10) * 0.5
        elif dd < 20:
            # Linear interpolation: 10% → 0.5, 20% → 0.25
            return 0.5 - ((dd - 10) / 10) * 0.25
        else:
            # Hard floor at 25% DD: 10% of nominal size
            return 0.1

    def get_regime_label(self) -> str:
        """Human-readable regime label."""
        dd = self.get_drawdown_pct()
        if dd < 2:
            return "STRONG (new high)"
        elif dd < 5:
            return "BULLISH (minor DD)"
        elif dd < 10:
            return "NEUTRAL (moderate DD)"
        elif dd < 15:
            return "CAUTIOUS (significant DD)"
        else:
            return "DEFENSIVE (severe DD)"


def scale_position_size(
    base_risk_pct: float,
    regime_sizer: RegimeAwareSizer,
    apply_scaling: bool = True,
) -> float:
    """
    Compute adjusted risk per trade given regime.

    Args:
        base_risk_pct: Nominal risk % (e.g., 1.0 = 1%)
        regime_sizer: Initialized RegimeAwareSizer
        apply_scaling: If False, returns base_risk_pct unchanged (disables regime scaling)

    Returns:
        Adjusted risk pct (product of base × multiplier)
    """
    if not apply_scaling:
        return base_risk_pct
    mult = regime_sizer.get_position_multiplier()
    return base_risk_pct * mult
