from execution.config import EXEC_SYMBOL_MAP, SYMBOL, SYMBOL_SPREAD_LIMITS


def normalize_symbol(symbol: str | None):
    if symbol is None:
        return ""
    return str(symbol).strip().upper()


def to_execution_symbol(symbol: str | None):
    normalized = normalize_symbol(symbol)
    if not normalized:
        return SYMBOL
    return EXEC_SYMBOL_MAP.get(normalized, normalized)


def is_execution_supported(symbol: str | None):
    execution_symbol = to_execution_symbol(symbol)
    return execution_symbol in SYMBOL_SPREAD_LIMITS
