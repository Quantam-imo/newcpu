def numerology_engine(price):
    num = sum(int(d) for d in str(int(price)))

    while num > 9:
        num = sum(int(d) for d in str(num))

    meaning = {
        1: "START",
        2: "BALANCE",
        3: "EXPANSION",
        4: "STRUCTURE",
        5: "CHANGE",
        6: "HARMONY",
        7: "REVERSAL",
        8: "POWER",
        9: "COMPLETION",
    }

    return {"number": num, "meaning": meaning[num]}