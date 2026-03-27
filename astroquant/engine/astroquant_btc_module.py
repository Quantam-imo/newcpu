# AstroQuant BTC Institutional Module
from astroquant.engine.databento_sync_engine import DatabentoSyncEngine
from astroquant.engine.ict_cme_gap_strategy import ICTCMEGapStrategy

class AstroQuantBTC:
    def __init__(self):
        self.sync_engine = DatabentoSyncEngine()
        self.strategy = ICTCMEGapStrategy(self.sync_engine)

    def get_signal(self):
        # Sync prices first
        self.sync_engine.fetch_all()
        # Generate institutional signal
        return self.strategy.generate_signal()

# Example usage
if __name__ == "__main__":
    aq_btc = AstroQuantBTC()
    print(aq_btc.get_signal())
