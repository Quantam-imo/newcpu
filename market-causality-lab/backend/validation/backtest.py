def backtest(memory):
    wins = 0
    losses = 0

    for i in range(50, len(memory) - 1):
        current = memory[i]
        next_move = memory[i + 1]["state"]["trend"]

        prediction = current["state"]["trend"]

        if prediction == next_move:
            wins += 1
        else:
            losses += 1

    total = wins + losses

    return {
        "winrate": wins / total if total else 0,
        "wins": wins,
        "losses": losses,
    }