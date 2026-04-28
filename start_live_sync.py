#!/usr/bin/env python3
import os
from pathlib import Path

from astroquant.engine.live_sync.live_sync_engine import LiveSyncEngine


def _disable_marker_path() -> Path:
    workspace = Path(__file__).resolve().parent
    return workspace / "data" / "logs" / "livesync.disabled"


def _write_disable_marker(reason: str) -> None:
    marker = _disable_marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(reason.strip() + "\n", encoding="utf-8")


def _clear_disable_marker() -> None:
    marker = _disable_marker_path()
    if marker.exists():
        marker.unlink()

if __name__ == "__main__":
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        print("[ERROR] DATABENTO_API_KEY not set in environment.")
        exit(1)
    # GCM6 = Gold June 2026 active contract (Databento GLBX.MDP3 live notation)
    # Update to GCQ6 after June 2026 contract expiry
    symbols = ["GCM6"]
    _clear_disable_marker()

    try:
        engine = LiveSyncEngine(api_key)
        engine.subscribe(symbols)
        engine.start()
    except Exception as exc:
        err = str(exc)
        if "authentication" in err.lower() or "unauthorized" in err.lower():
            reason = f"disabled_due_to_databento_auth_failure: {err}"
            print(f"[LIVE SYNC] {reason}")
            _write_disable_marker(reason)
            raise SystemExit(0)
        raise
