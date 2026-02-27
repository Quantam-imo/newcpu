import datetime

class AstroEngine:

    def analyze(self):
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        day_of_year = now_utc.timetuple().tm_yday
        weekday = now_utc.weekday()
        utc_hour = now_utc.hour

        harmonic = day_of_year % 9

        score = 10
        if harmonic in [2, 3, 6]:
            score += 18
        if weekday in [1, 2, 3]:
            score += 6
        if utc_hour in [7, 8, 9, 13, 14, 15]:
            score += 8

        phase = "Expansion" if harmonic in [2, 3, 6] else "Compression"
        window = "07:00–10:00 UTC" if utc_hour < 12 else "13:00–16:00 UTC"
        volatility_bias = "High" if score >= 30 else "Normal"

        return {
            "astro_score": min(int(score), 100),
            "harmonic": harmonic,
            "phase": phase,
            "window": window,
            "volatility_bias": volatility_bias,
        }
