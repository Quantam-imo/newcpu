class CycleEngine:

    def __init__(self):
        self.major_cycles = [21, 45, 90, 180]

    def analyze(self, bars):
        bar_count = len(bars or [])
        if bar_count <= 0:
            return {
                "bar_count": 0,
                "is_cycle": False,
                "active_cycles": [],
                "next_cycle": self.major_cycles[0],
                "phase": "Build-up",
            }

        active_cycles = [cycle for cycle in self.major_cycles if bar_count % cycle == 0]
        next_cycle = next((cycle for cycle in self.major_cycles if cycle > bar_count), self.major_cycles[-1])

        if active_cycles:
            phase = "Inflection"
        elif bar_count % 10 >= 7:
            phase = "Late"
        elif bar_count % 10 >= 4:
            phase = "Mid"
        else:
            phase = "Early"

        return {
            "bar_count": bar_count,
            "is_cycle": bool(active_cycles),
            "active_cycles": active_cycles,
            "next_cycle": next_cycle,
            "phase": phase,
        }
