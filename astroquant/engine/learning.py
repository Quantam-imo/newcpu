class LearningEngine:

	def __init__(self, meta_model=None):
		self.model_performance = {}
		self.meta_model = meta_model  # Optional meta-learner for stacking

	def update(self, model, win):
		if model not in self.model_performance:
			self.model_performance[model] = {"wins": 0, "losses": 0}
		if win:
			self.model_performance[model]["wins"] += 1
		else:
			self.model_performance[model]["losses"] += 1
		# Optionally retrain meta-model online
		if self.meta_model:
			self.retrain_meta_model()

	def get_weight(self, model):
		stats = self.model_performance.get(model)
		if not stats:
			return 1.0
		total = stats["wins"] + stats["losses"]
		if total == 0:
			return 1.0
		win_rate = stats["wins"] / total
		return 0.8 + (win_rate * 0.4)  # dynamic weight

	def retrain_meta_model(self):
		# Retrain meta-model with recent trade data (example: load from JSON or DB)
		if not self.meta_model:
			return
		import json
		import os
		trade_data_path = os.path.join(os.path.dirname(__file__), "../../data/performance_memory.json")
		try:
			with open(trade_data_path, "r") as f:
				trades = json.load(f)
			# Assume trades is a list of dicts with features and outcome
			X = [t["features"] for t in trades if "features" in t]
			y = [t["outcome"] for t in trades if "outcome" in t]
			if X and y:
				self.meta_model.fit(X, y)
		except Exception as exc:
			print(f"[LearningEngine] Meta-model retrain failed: {exc}")
