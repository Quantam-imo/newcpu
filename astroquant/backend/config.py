import os
from pathlib import Path


def _load_env_file():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_env_file()


ACCOUNT_CONFIG = {
    "initial_balance": 50000,
    "daily_limit": 1500,
    "max_drawdown": 4000,
    "funded_floor": 52000,
    "risk_per_trade_phase1": 0.005,
    "risk_per_trade_phase2": 0.007,
    "risk_per_trade_funded": 0.01
}

SYMBOLS = {
    "XAUUSD": {"databento": "GC.FUT", "priority_models": ["ICT", "ICEBERG"], "dataset": "GLBX.MDP3"},
    "NQ": {"databento": "NQ.FUT", "priority_models": ["EXPANSION", "ICEBERG"], "dataset": "GLBX.MDP3"},
    "EURUSD": {"databento": "6E.FUT", "priority_models": ["ICT"], "dataset": "GLBX.MDP3"},
    "BTC": {"databento": "BTC.FUT", "priority_models": ["EXPANSION"], "dataset": "GLBX.MDP3"},
    "US30": {"databento": "YM.FUT", "priority_models": ["ICT"], "dataset": "GLBX.MDP3"}
}

DATABENTO_API_KEY = os.getenv("DATABENTO_API_KEY", "").strip()
DATABENTO_DATASET = os.getenv("DATABENTO_DATASET", "GLBX.MDP3").strip() or "GLBX.MDP3"
DATABENTO_STRICT_STARTUP = os.getenv("DATABENTO_STRICT_STARTUP", "false").strip().lower() in {"1", "true", "yes", "on"}
SPOT_FIDELITY_SYMBOLS = [
    s.strip().upper() for s in os.getenv("SPOT_FIDELITY_SYMBOLS", "XAUUSD").split(",") if s.strip()
]
SPOT_FIDELITY_STRICT = os.getenv("SPOT_FIDELITY_STRICT", "true").strip().lower() in {"1", "true", "yes", "on"}
SPOT_CONFIRMATION_MAX_BPS = float(os.getenv("SPOT_CONFIRMATION_MAX_BPS", "120"))
EXECUTION_BROWSER_AUTO_ATTACH = os.getenv("EXECUTION_BROWSER_AUTO_ATTACH", "false").strip().lower() in {"1", "true", "yes", "on"}
EXECUTION_BROWSER_CDP_URL = os.getenv("EXECUTION_BROWSER_CDP_URL", "").strip()
EXECUTION_BROWSER_USER_DATA_DIR = os.getenv("EXECUTION_BROWSER_USER_DATA_DIR", "").strip()
EXECUTION_BROWSER_HEADLESS = os.getenv("EXECUTION_BROWSER_HEADLESS", "true").strip().lower() in {"1", "true", "yes", "on"}
EXECUTION_BROWSER_URL = os.getenv("EXECUTION_BROWSER_URL", "https://manager.maven.markets/app/trade").strip()
EXECUTION_BROWSER_TIMEOUT_MS = int(os.getenv("EXECUTION_BROWSER_TIMEOUT_MS", "12000"))
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "dev-admin-token").strip() or "dev-admin-token"
ADMIN_DEFAULT_ROLE = os.getenv("ADMIN_DEFAULT_ROLE", "ADMIN").strip().upper() or "ADMIN"


def symbol_dataset(symbol: str) -> str:
    profile = SYMBOLS.get(symbol, {})
    dataset = str(profile.get("dataset") or "").strip()
    return dataset or DATABENTO_DATASET
