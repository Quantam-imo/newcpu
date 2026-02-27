import os

from dotenv import load_dotenv


load_dotenv()


def _parse_kv_map(raw_value):
	mapping = {}
	if not raw_value:
		return mapping

	for item in str(raw_value).split(","):
		pair = item.strip()
		if not pair or ":" not in pair:
			continue
		key, value = pair.split(":", 1)
		key_norm = key.strip().upper()
		value_norm = value.strip().upper()
		if key_norm and value_norm:
			mapping[key_norm] = value_norm

	return mapping


def _parse_spread_limits(raw_value):
	parsed = {}
	for symbol, value in _parse_kv_map(raw_value).items():
		try:
			parsed[symbol] = int(float(value))
		except Exception:
			continue
	return parsed


SYMBOL = os.getenv("EXEC_DEFAULT_SYMBOL", "XAUUSD").strip().upper() or "XAUUSD"
LOT_SIZE = os.getenv("EXEC_LOT_SIZE", "1")

STOP_LOSS_POINTS = int(float(os.getenv("EXEC_STOP_LOSS_POINTS", "150")))
TAKE_PROFIT_POINTS = int(float(os.getenv("EXEC_TAKE_PROFIT_POINTS", "300")))


def dynamic_lot(balance, risk_percent, sl_points):
	risk_amount = balance * risk_percent
	lot = risk_amount / (sl_points * 10)
	return round(max(lot, 0.01), 2)


SYMBOL_SPREAD_LIMITS = {
	"XAUUSD": 30,
	"EURUSD": 10,
	"GBPUSD": 12,
	"NAS100": 50,
	"US30": 70,
	"USOIL": 80,
}

SYMBOL_SPREAD_LIMITS.update(_parse_spread_limits(os.getenv("EXEC_SPREAD_LIMITS", "")))


EXEC_SYMBOL_MAP = {
	"GC-F": "XAUUSD",
	"GC.FUT": "XAUUSD",
	"GC": "XAUUSD",
	"GCZ6": "XAUUSD",
	"NQ.FUT": "NAS100",
	"ESZ6": "NAS100",
	"YM.FUT": "US30",
	"CLZ6": "USOIL",
	"CL.FUT": "USOIL",
	"6E.FUT": "EURUSD",
	"6B.FUT": "GBPUSD",
	"XAUUSD": "XAUUSD",
	"NAS100": "NAS100",
	"US30": "US30",
	"EURUSD": "EURUSD",
	"GBPUSD": "GBPUSD",
	"USOIL": "USOIL",
}

EXEC_SYMBOL_MAP.update(_parse_kv_map(os.getenv("EXEC_SYMBOL_MAP", "")))


TRADE_UNIVERSE = [
	{"broker_symbol": "XAUUSD", "data_symbol": "GC.FUT", "priority": "PRIMARY"},
	{"broker_symbol": "NAS100", "data_symbol": "NQ.FUT", "priority": "HIGH"},
	{"broker_symbol": "US30", "data_symbol": "YM.FUT", "priority": "MEDIUM"},
	{"broker_symbol": "EURUSD", "data_symbol": "6E.FUT", "priority": "STABLE"},
	{"broker_symbol": "GBPUSD", "data_symbol": "6B.FUT", "priority": "VOLATILE"},
	{"broker_symbol": "USOIL", "data_symbol": "CL.FUT", "priority": "NEWS-BASED"},
]

PRIORITY_RULES = {
	"PRIMARY": {"min_confidence": 72, "min_model_votes": 3},
	"HIGH": {"min_confidence": 75, "min_model_votes": 3},
	"MEDIUM": {"min_confidence": 78, "min_model_votes": 4},
	"STABLE": {"min_confidence": 74, "min_model_votes": 3},
	"VOLATILE": {"min_confidence": 82, "min_model_votes": 4},
	"NEWS-BASED": {"min_confidence": 84, "min_model_votes": 4},
}
