class GannCrossEngine:
    cardinal = [0, 90, 180, 270, 360]
    ordinal = [45, 135, 225, 315]

    def classify(self, degree, tolerance=3.0):
        try:
            value = float(degree)
        except Exception:
            return None

        d = value % 360.0
        for level in self.cardinal:
            if abs(d - level) <= float(tolerance):
                return "CARDINAL"
        for level in self.ordinal:
            if abs(d - level) <= float(tolerance):
                return "ORDINAL"
        return None
