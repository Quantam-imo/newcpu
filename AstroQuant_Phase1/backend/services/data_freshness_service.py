import os


DEFAULT_STALENESS_SECONDS = 300

DEFAULT_SYMBOL_STALENESS = {
    "GC": 300,
    "NQ": 180,
    "ES": 180,
    "YM": 180,
    "CL": 360,
    "6E": 480,
    "6B": 480,
}


def _normalize_root(symbol: str):
    normalized = str(symbol or "").strip().upper()
    if not normalized:
        return ""

    if normalized.startswith("GC") or normalized == "XAUUSD":
        return "GC"
    if normalized.startswith("NQ") or normalized == "NAS100":
        return "NQ"
    if normalized.startswith("YM") or normalized == "US30":
        return "YM"
    if normalized.startswith("CL") or normalized == "USOIL":
        return "CL"
    if normalized.startswith("6E") or normalized == "EURUSD":
        return "6E"
    if normalized.startswith("6B") or normalized == "GBPUSD":
        return "6B"

    if "." in normalized:
        return normalized.split(".", 1)[0]
    return normalized


def _parse_staleness_env(value: str):
    parsed = {}
    for item in str(value or "").split(","):
        entry = item.strip()
        if not entry or ":" not in entry:
            continue
        key, raw_seconds = entry.split(":", 1)
        normalized_key = _normalize_root(key)
        if str(key).strip().upper() == "DEFAULT":
            normalized_key = "DEFAULT"
        if not normalized_key:
            continue

        try:
            seconds = int(float(raw_seconds.strip()))
        except Exception:
            continue

        if seconds <= 0:
            continue
        parsed[normalized_key] = seconds

    return parsed


def staleness_limit_for(symbol: str, default_seconds: int = DEFAULT_STALENESS_SECONDS):
    env_map = _parse_staleness_env(os.getenv("DATA_STALENESS_SECONDS", ""))
    root = _normalize_root(symbol)

    baseline_default = DEFAULT_SYMBOL_STALENESS.get(root, default_seconds)
    default_limit = int(env_map.get("DEFAULT", baseline_default) or baseline_default)

    if root and root in env_map:
        return int(env_map[root])

    return default_limit
