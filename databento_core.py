import databento as db
from typing import Tuple, Optional

SYMBOL_TYPE_MAP = {
    # Add more mappings as needed
    "ES.c.0": "continuous",
    "GC.c.0": "continuous",
    # Example: instrument IDs or other types can be added here
}

def resolve_symbol_and_type(symbol: str) -> Tuple[str, Optional[str]]:
    """
    Resolves the Databento symbol and stype_in for the Historical API.
    Returns (symbol, stype_in) tuple.
    """
    stype_in = SYMBOL_TYPE_MAP.get(symbol)
    return symbol, stype_in

def fetch_historical_data(symbol: str, start: str, end: str, schema: str = "trades", dataset: str = "GLBX.MDP3", api_key: Optional[str] = None, limit: Optional[int] = None) -> object:
    symbol, stype_in = resolve_symbol_and_type(symbol)
    client = db.Historical(api_key) if api_key else db.Historical()
    kwargs = dict(dataset=dataset, schema=schema, symbols=[symbol], start=start, end=end)
    if stype_in:
        kwargs["stype_in"] = stype_in
    if limit:
        kwargs["limit"] = limit
    return client.timeseries.get_range(**kwargs)