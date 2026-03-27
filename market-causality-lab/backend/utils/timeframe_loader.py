from pathlib import Path

from backend.utils.data_loader import load_data


TIMEFRAME_FILES = {
    "1m": "XAU_1m_data.csv",
    "5m": "XAU_5m_data.csv",
    "15m": "XAU_15m_data.csv",
    "30m": "XAU_30m_data.csv",
    "1h": "XAU_1h_data.csv",
    "4h": "XAU_4h_data.csv",
    "1d": "XAU_1d_data.csv",
    "1w": "XAU_1w_data.csv",
    "1month": "XAU_1Month_data.csv",
}


def load_available_timeframes(data_dir: str = "data"):
    base = Path(data_dir)
    frames = {}
    missing = {}

    for timeframe, filename in TIMEFRAME_FILES.items():
        path = base / filename
        if path.exists():
            frames[timeframe] = load_data(str(path))
        else:
            missing[timeframe] = filename

    return frames, missing