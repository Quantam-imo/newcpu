import json


def save_memory(memory, path="data/memory.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(memory, f, default=str)