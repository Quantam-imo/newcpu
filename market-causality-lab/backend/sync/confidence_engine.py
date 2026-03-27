def confidence_engine(score):
    total = score["BUY"] + score["SELL"]

    if total == 0:
        return 0.5

    confidence = max(score.values()) / total

    return round(confidence, 2)