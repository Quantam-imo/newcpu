# Consensus Engine for AstroQuant

class ConsensusEngine:
    """
    Combines signals from multiple models (ICT, Gann, Iceberg, News, etc.)
    to produce a consensus trading decision.
    """
    def __init__(self, models):
        self.models = models  # List of model instances

    def get_consensus_signal(self, market_data):
        signals = {}
        for model in self.models:
            name = model.__class__.__name__
            try:
                signals[name] = model.get_signal(market_data)
            except Exception as e:
                signals[name] = None
        # Simple voting mechanism: majority wins, ignore None
        votes = [s for s in signals.values() if s is not None]
        if not votes:
            return None
        return max(set(votes), key=votes.count)
