import os
from pathlib import Path


def _env_first(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return str(default).strip()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(*names: str, default: int = 0) -> int:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        try:
            return int(float(text))
        except Exception:
            continue
    return int(default)


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
    "XAUUSD": {"databento": "GC.c.1", "priority_models": ["ICT", "ICEBERG"], "dataset": "GLBX.MDP3"},
    "GC-F": {"databento": "GC.c.1", "priority_models": ["ICT", "ICEBERG"], "dataset": "GLBX.MDP3"},
    "NQ": {"databento": "NQ.c.1", "priority_models": ["EXPANSION", "ICEBERG"], "dataset": "GLBX.MDP3"},
    "EURUSD": {"databento": "6E.c.1", "priority_models": ["ICT"], "dataset": "GLBX.MDP3"},
    "BTC": {"databento": "BTC.c.1", "priority_models": ["EXPANSION"], "dataset": "GLBX.MDP3"},
    "US30": {"databento": "YM.c.1", "priority_models": ["ICT"], "dataset": "GLBX.MDP3"}
}

DATABENTO_API_KEY = os.getenv("DATABENTO_API_KEY", "").strip()
DATABENTO_DATASET = os.getenv("DATABENTO_DATASET", "GLBX.MDP3").strip() or "GLBX.MDP3"
DATABENTO_STRICT_STARTUP = os.getenv("DATABENTO_STRICT_STARTUP", "false").strip().lower() in {"1", "true", "yes", "on"}
SPOT_FIDELITY_SYMBOLS = [
    s.strip().upper() for s in os.getenv("SPOT_FIDELITY_SYMBOLS", "XAUUSD").split(",") if s.strip()
]
SPOT_FIDELITY_STRICT = os.getenv("SPOT_FIDELITY_STRICT", "true").strip().lower() in {"1", "true", "yes", "on"}
SPOT_CONFIRMATION_MAX_BPS = float(os.getenv("SPOT_CONFIRMATION_MAX_BPS", "120"))
EXECUTION_BROWSER_CDP_URL = _env_first("EXECUTION_BROWSER_CDP_URL", "CDP_ENDPOINT")
EXECUTION_BROWSER_USER_DATA_DIR = _env_first(
    "EXECUTION_BROWSER_USER_DATA_DIR",
    "PLAYWRIGHT_USER_DATA_DIR",
    "BROWSER_PROFILE_DIR",
)
EXECUTION_BROWSER_AUTO_ATTACH = _env_flag(
    "EXECUTION_BROWSER_AUTO_ATTACH",
    default=bool(EXECUTION_BROWSER_CDP_URL or EXECUTION_BROWSER_USER_DATA_DIR),
)
EXECUTION_BROWSER_HEADLESS = os.getenv("EXECUTION_BROWSER_HEADLESS", "true").strip().lower() in {"1", "true", "yes", "on"}
EXECUTION_BROWSER_URL = os.getenv("EXECUTION_BROWSER_URL", "https://manager.maven.markets/app/trade").strip()
EXECUTION_BROWSER_TIMEOUT_MS = _env_int(
    "EXECUTION_BROWSER_TIMEOUT_MS",
    default=_env_int("CDP_TIMEOUT_SEC", default=12) * 1000,
)
EXECUTION_LOGIN_USERNAME = os.getenv("EXECUTION_LOGIN_USERNAME", os.getenv("MAVEN_USERNAME", "")).strip()
EXECUTION_LOGIN_PASSWORD = os.getenv("EXECUTION_LOGIN_PASSWORD", os.getenv("MAVEN_PASSWORD", "")).strip()
ADMIN_API_TOKEN = os.getenv("ADMIN_API_TOKEN", "dev-admin-token").strip() or "dev-admin-token"
ADMIN_DEFAULT_ROLE = os.getenv("ADMIN_DEFAULT_ROLE", "ADMIN").strip().upper() or "ADMIN"


def symbol_dataset(symbol: str) -> str:
    profile = SYMBOLS.get(symbol, {})
    dataset = str(profile.get("dataset") or "").strip()
    return dataset or DATABENTO_DATASET
