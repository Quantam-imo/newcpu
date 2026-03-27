def update_memory(memory, new_record):
    memory.append(new_record)

    # Keep last N records (avoid overload)
    if len(memory) > 100000:
        memory = memory[-100000:]

    return memory