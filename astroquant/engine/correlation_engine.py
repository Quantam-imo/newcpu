class CorrelationEngine:

    def __init__(self):
        self.correlated_groups = [
            ["XAUUSD", "US30", "NQ", "EURUSD"]
        ]

    def portfolio_heat(self, open_positions):
        heat = 0
        symbols = list(open_positions.keys()) if isinstance(open_positions, dict) else list(open_positions)

        for group in self.correlated_groups:
            group_exposure = sum(1 for symbol in symbols if symbol in group)
            if group_exposure > 1:
                heat += group_exposure

        return heat
