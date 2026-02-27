class LearningEngine:

    def adjust_confidence_threshold(self, performance, governance):

        if performance["win_rate"] < 40:
            governance.min_confidence_required += 5

        if performance["win_rate"] > 65:
            governance.min_confidence_required -= 5

        governance.min_confidence_required = max(
            50,
            min(governance.min_confidence_required, 80)
        )
