def dominance_engine(signals, weights):
    score = {"BUY": 0, "SELL": 0}

    for key, signal in signals.items():
        if signal in score:
            score[signal] += weights.get(key, 1)

    dominant = max(score, key=score.get)

    return dominant, score