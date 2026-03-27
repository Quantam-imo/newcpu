# Consensus Engine for AstroQuant

class ConsensusEngine:
    """
    Combines signals from multiple models (ICT, Gann, Iceberg, News, etc.)
    to produce a consensus trading decision.
    """
    def __init__(self, models, model_weight_engine=None, meta_model=None):
        self.models = models  # List of model instances
        self.model_weight_engine = model_weight_engine
        self.meta_model = meta_model  # Optional meta-learner for stacking

    def get_consensus_signal(self, market_data):
        signals = {}
        weights = {}
        for model in self.models:
            name = model.__class__.__name__
            try:
                signals[name] = model.get_signal(market_data)
            except Exception as e:
                signals[name] = None
            # Get model weight if available
            if self.model_weight_engine:
                weights[name] = self.model_weight_engine.model_weight(name)
            else:
                weights[name] = 1.0

        # If meta_model (stacked ensemble) is provided, use it
        if self.meta_model:
            # Meta-model expects a feature vector of model outputs
            meta_input = [signals.get(model.__class__.__name__) for model in self.models]
            return self.meta_model.predict(meta_input)

        # Weighted voting ensemble
        vote_scores = {}
        for name, signal in signals.items():
            if signal is not None:
                vote_scores[signal] = vote_scores.get(signal, 0) + weights.get(name, 1.0)
        if not vote_scores:
            return None
        # Return the signal with the highest weighted score
        return max(vote_scores, key=vote_scores.get)
