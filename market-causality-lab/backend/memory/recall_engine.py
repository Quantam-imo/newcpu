def recall_patterns(matches, memory):
    results = []

    for idx, score in matches:
        record = memory[idx]

        results.append(
            {"score": score, "phase": record["phase"], "trend": record["state"]["trend"]}
        )

    return results