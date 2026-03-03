class PositionManager:

    def __init__(self, state):
        self.state = state

    def has_open_position(self, symbol):
        return symbol in self.state.open_positions

    def add_position(self, symbol, trade):
        self.state.open_positions[symbol] = trade

    def close_position(self, symbol):
        if symbol in self.state.open_positions:
            del self.state.open_positions[symbol]

    def get_positions(self):
        return self.state.open_positions
