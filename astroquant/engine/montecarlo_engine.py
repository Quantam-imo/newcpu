import random


class MonteCarlo:

    def simulate(self, win_rate=0.55, rr=2, trades=100):
        equity = 0
        results = []

        for _ in range(trades):
            if random.random() < win_rate:
                equity += rr
            else:
                equity -= 1
            results.append(equity)

        return min(results), max(results)
