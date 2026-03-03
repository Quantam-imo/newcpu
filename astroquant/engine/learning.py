class LearningEngine:

	def __init__(self):
		self.model_performance = {}

	def update(self, model, win):

		if model not in self.model_performance:
			self.model_performance[model] = {"wins": 0, "losses": 0}

		if win:
			self.model_performance[model]["wins"] += 1
		else:
			self.model_performance[model]["losses"] += 1

	def get_weight(self, model):
		stats = self.model_performance.get(model)

		if not stats:
			return 1.0

		total = stats["wins"] + stats["losses"]

		if total == 0:
			return 1.0

		win_rate = stats["wins"] / total

		return 0.8 + (win_rate * 0.4)  # dynamic weight
