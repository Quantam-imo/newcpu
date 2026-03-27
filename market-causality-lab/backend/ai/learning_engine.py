def learning_engine(prediction, actual, weights):
    # Compare prediction vs real outcome
    if prediction == actual:
        reward = 1
    else:
        reward = -1

    # Adjust weights
    for k in weights:
        weights[k] += 0.1 * reward

    return weights