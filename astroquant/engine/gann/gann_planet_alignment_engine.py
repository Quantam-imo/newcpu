from datetime import datetime, timezone


class GannPlanetAlignmentEngine:
    CYCLES = {
        "mercury": 88,
        "venus": 225,
        "earth": 365,
        "mars": 687,
    }

    def _epoch_day(self, timestamp=None):
        if timestamp is None:
            now = datetime.now(timezone.utc)
            return int(now.timestamp() // 86400)

        if isinstance(timestamp, (int, float)):
            return int(float(timestamp) // 86400)

        try:
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            return int(parsed.timestamp() // 86400)
        except Exception:
            now = datetime.now(timezone.utc)
            return int(now.timestamp() // 86400)

    def evaluate(self, timestamp=None, window_days=2):
        day = self._epoch_day(timestamp)
        window = max(0, int(window_days))

        alignments = {}
        score = 0
        for name, cycle in self.CYCLES.items():
            rem = day % int(cycle)
            distance = min(rem, int(cycle) - rem)
            aligned = distance <= window
            if aligned:
                score += 1
            alignments[name] = {
                "distance": int(distance),
                "aligned": bool(aligned),
            }

        return {
            "score": int(score),
            "alignments": alignments,
            "window_days": window,
        }
