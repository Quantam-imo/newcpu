from __future__ import annotations

from collections import deque


class BasisEngine:

    def __init__(self, window: int = 30):
        self.window = max(5, int(window))
        self.rolling_basis = deque(maxlen=self.window)

    def update(self, futures_price: float, broker_price: float):
        basis = float(broker_price) - float(futures_price)
        self.rolling_basis.append(basis)

    def get_smoothed_basis(self) -> float:
        if not self.rolling_basis:
            return 0.0
        return sum(self.rolling_basis) / float(len(self.rolling_basis))

    def convert_signal(self, futures_signal: dict) -> dict:
        basis = self.get_smoothed_basis()
        return {
            "direction": futures_signal["direction"],
            "broker_entry": float(futures_signal["entry"]) + basis,
            "broker_sl": float(futures_signal["stop"]) + basis,
            "broker_tp": float(futures_signal["target"]) + basis,
            "lot": float(futures_signal["lot"]),
            "basis": basis,
        }
