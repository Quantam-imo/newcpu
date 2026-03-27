def compute_probability(results):
    up = 0
    down = 0

    for r in results:
        if r["trend"] == "UP":
            up += 1
        else:
            down += 1

    total = up + down

    if total == 0:
        return {"BUY": 0.5, "SELL": 0.5}

    return {"BUY": up / total, "SELL": down / total}