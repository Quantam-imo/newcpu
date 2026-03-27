import numpy as np


def cosine_similarity(a, b):
    a = np.array(a, dtype=float)
    b = np.array(b, dtype=float)

    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0

    return float(np.dot(a, b) / denom)


def find_similar(current_vec, memory_vectors, top_n=5):
    scores = []

    for i, vec in enumerate(memory_vectors):
        sim = cosine_similarity(current_vec, vec)
        scores.append((i, sim))

    scores.sort(key=lambda x: x[1], reverse=True)

    return scores[:top_n]