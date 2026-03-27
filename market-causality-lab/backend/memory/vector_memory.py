from backend.ai.feature_vector import create_feature_vector


def build_vector_memory(memory):
    vectors = []

    for record in memory:
        vec = create_feature_vector(record)
        vectors.append(vec)

    return vectors