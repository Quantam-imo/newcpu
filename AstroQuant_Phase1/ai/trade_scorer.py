class TradeScorer:

    def score(self, fusion, ict, gann, astro, iceberg):

        score = fusion["confidence"]

        if ict["ict_score"] != 0:
            score += 5

        if gann["gann_score"] > 20:
            score += 5

        if astro["astro_score"] > 0:
            score += 5

        if iceberg:
            score += 10

        return min(score, 100)
