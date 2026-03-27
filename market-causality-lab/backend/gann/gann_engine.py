import math


def price_to_degree(price):
    return (math.sqrt(price) * 180) % 360


def gann_engine(state):
    degree = price_to_degree(state["price"])

    return {"degree": degree, "zone": "REVERSAL" if 170 < degree < 190 else "NORMAL"}