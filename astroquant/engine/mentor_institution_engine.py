from __future__ import annotations


class MentorInstitutionEngine:
    def analyze(self, market: dict) -> dict:
        return {
            "iceberg_buy": float(market.get("iceberg_buy") or 0.0),
            "iceberg_sell": float(market.get("iceberg_sell") or 0.0),
            "delta": float(market.get("delta") or 0.0),
            "poc": float(market.get("poc") or 0.0),
        }
