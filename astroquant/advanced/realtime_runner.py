"""Simple CLI runner for the advanced real-time engine."""
from __future__ import annotations

import json
import os

from astroquant.advanced.realtime_data_engine import RealTimeDataEngine, FeedConfig


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    """Parse integer env vars with bounds and safe fallback."""
    raw = os.getenv(name, str(default))
    try:
        value = int(str(raw).strip())
    except Exception:
        value = int(default)

    if minimum is not None:
        value = max(int(minimum), value)
    if maximum is not None:
        value = min(int(maximum), value)
    return value


def main() -> None:
    cfg = FeedConfig(
        dataset=os.getenv("AQ_DATASET", "GLBX.MDP3"),
        symbol=os.getenv("AQ_SYMBOL", "GC.c.0"),
        lookback_minutes=_env_int("AQ_LOOKBACK_MIN", 240, minimum=1, maximum=7 * 24 * 60),
        poll_seconds=_env_int("AQ_POLL_SEC", 15, minimum=1, maximum=3600),
    )
    engine = RealTimeDataEngine(feed_config=cfg)

    def _printer(snapshot: dict) -> None:
        print(json.dumps(snapshot, default=str))

    max_iter = _env_int("AQ_MAX_ITER", 1, minimum=1)
    engine.run_forever(on_signal=_printer, max_iterations=max_iter)


if __name__ == "__main__":
    main()
