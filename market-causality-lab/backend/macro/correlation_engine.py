import numpy as np


def correlation_engine(asset1, asset2):
    corr = np.corrcoef(asset1, asset2)[0, 1]

    if corr < -0.5:
        return "INVERSE"

    if corr > 0.5:
        return "DIRECT"

    return "WEAK"