"""
AstroQuant Symbol + Rollover Engine
Institutional-grade: auto contract switching, multi-market sync (GC, ES), front-month logic.
"""
import databento as db
from datetime import datetime, timezone
from typing import List, Dict, Optional

class SymbolRolloverEngine:
    def __init__(self, api_key: Optional[str] = None, dataset: str = "GLBX.MDP3"):
        import os
        self.api_key = api_key or os.getenv("DATABENTO_API_KEY")
        if not self.api_key:
            raise ValueError("API key is missing. Set DATABENTO_API_KEY env variable or pass api_key explicitly.")
        self.dataset = dataset
        self.client = db.Historical(self.api_key)
        self._instrument_cache = None

    def fetch_instruments(self, root: str) -> List[Dict]:
        """
        Fetch all valid instruments for a given root (e.g., 'GC', 'ES').
        Returns a list of instrument dicts.
        """
        instruments = self.client.reference.get_instruments(dataset=self.dataset, symbols=root)
        # Filter for futures contracts only
        return [inst for inst in instruments if inst.get("root") == root]

    def get_front_month(self, root: str, as_of: Optional[datetime] = None) -> Optional[str]:
        """
        Return the front-month contract symbol for a given root as of a date.
        """
        if as_of is None:
            as_of = datetime.now(timezone.utc)
        instruments = self.fetch_instruments(root)
        # Filter for contracts not expired as of 'as_of'
        valid = [inst for inst in instruments if "expiration" in inst and (not inst["expiration"] or datetime.fromisoformat(inst["expiration"]) > as_of)]
        # Sort by expiration date ascending (soonest first)
        valid = sorted(valid, key=lambda x: x.get("expiration") or "9999-12-31")
        if valid:
            return valid[0]["symbol"]
        return None

    def get_active_contracts(self, root: str, n: int = 3, as_of: Optional[datetime] = None) -> List[str]:
        """
        Return up to n active contracts for a root, ordered by expiration.
        """
        if as_of is None:
            as_of = datetime.now(timezone.utc)
        instruments = self.fetch_instruments(root)
        valid = [inst for inst in instruments if "expiration" in inst and (not inst["expiration"] or datetime.fromisoformat(inst["expiration"]) > as_of)]
        valid = sorted(valid, key=lambda x: x.get("expiration") or "9999-12-31")
        return [inst["symbol"] for inst in valid[:n]]

    def get_multi_market_front_months(self, roots: List[str], as_of: Optional[datetime] = None) -> Dict[str, str]:
        """
        Return a dict of {root: front_month_symbol} for each root.
        """
        return {root: self.get_front_month(root, as_of) for root in roots}

# Example usage/test
if __name__ == "__main__":
    engine = SymbolRolloverEngine()
    # Gold (GC) contracts
    gc_contracts = engine.get_active_contracts("GC", n=3)
    print("GC contracts (active):", gc_contracts)
    # S&P (ES) contracts
    es_contracts = engine.get_active_contracts("ES", n=2)
    print("ES contracts (active):", es_contracts)
    # Front months
    front_months = engine.get_multi_market_front_months(["GC", "ES"])
    print("Front months:", front_months)