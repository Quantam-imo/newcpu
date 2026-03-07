from __future__ import annotations


class VolumeProfileEngine:
    @staticmethod
    def _field(row, key, default=None):
        if isinstance(row, dict):
            return row.get(key, default)
        return getattr(row, key, default)

    @staticmethod
    def _to_float(value, default=0.0):
        try:
            return float(value)
        except Exception:
            return float(default)

    def build_profile(self, trades):
        profile = {}
        for trade in list(trades or []):
            price = self._to_float(self._field(trade, "price", 0.0), 0.0)
            size = self._to_float(self._field(trade, "size", 0.0), 0.0)
            if price <= 0.0 or size <= 0.0:
                continue
            bucket = round(price, 2)
            profile[bucket] = self._to_float(profile.get(bucket, 0.0), 0.0) + size
        return profile

    def point_of_control(self, trades):
        profile = self.build_profile(trades)
        if not profile:
            return None
        return max(profile, key=lambda p: profile[p])

    def value_area(self, trades, ratio=0.70):
        profile = self.build_profile(trades)
        if not profile:
            return {"vah": None, "val": None, "poc": None}

        total = sum(float(v) for v in profile.values())
        target = max(0.0, min(1.0, float(ratio))) * total
        poc = self.point_of_control(trades)

        ordered = sorted(profile.items(), key=lambda item: item[0])
        prices = [p for p, _ in ordered]
        idx = prices.index(poc)
        selected = {poc}
        running = float(profile.get(poc, 0.0))
        left = idx - 1
        right = idx + 1

        while running < target and (left >= 0 or right < len(ordered)):
            left_vol = ordered[left][1] if left >= 0 else -1.0
            right_vol = ordered[right][1] if right < len(ordered) else -1.0
            if right_vol >= left_vol and right < len(ordered):
                selected.add(ordered[right][0])
                running += float(ordered[right][1])
                right += 1
            elif left >= 0:
                selected.add(ordered[left][0])
                running += float(ordered[left][1])
                left -= 1
            else:
                break

        return {
            "poc": float(poc),
            "vah": float(max(selected)),
            "val": float(min(selected)),
        }
