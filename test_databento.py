import os
import time
from datetime import datetime, timedelta, timezone

import databento as db



import pytest

@pytest.mark.parametrize("candidates", [["GCJ6", "GCM6", "GCZ6", "GC.c.1"]])
def test_historical_bbo(candidates):
    key = os.getenv("DATABENTO_API_KEY")
    assert key, "DATABENTO_API_KEY is not set"
    client = db.Historical(key)
    now = datetime.now(timezone.utc)
    end = now - timedelta(minutes=20)
    start = end - timedelta(minutes=30)
    for symbol in candidates:
        try:
            store = client.timeseries.get_range(
                dataset="GLBX.MDP3",
                symbols=[symbol],
                schema="bbo-1s",
                start=start.isoformat(),
                end=end.isoformat(),
            )
            rows = list(store)
            if rows:
                print(f"HIST OK {symbol}: rows={len(rows)} window={start.isoformat()} -> {end.isoformat()}", flush=True)
                return
            print(f"HIST NO_DATA {symbol}: rows=0", flush=True)
        except Exception as exc:
            first_line = str(exc).splitlines()[0]
            print(f"HIST FAIL {symbol}: {first_line}", flush=True)
    pytest.fail("No historical BBO data found for any candidate symbol.")



@pytest.mark.parametrize("symbol", ["GC.c.1"])
def test_live_bbo(symbol, listen_seconds=6):
    key = os.getenv("DATABENTO_API_KEY")
    assert key, "DATABENTO_API_KEY is not set"
    seen = {"count": 0}

    def on_record(_record):
        seen["count"] += 1

    def on_error(exc):
        print(f"LIVE ERROR CALLBACK {symbol}: {exc}", flush=True)

    live = None
    try:
        live = db.Live(key=key)
        live.add_callback(on_record, on_error)
        live.subscribe(
            dataset="GLBX.MDP3",
            schema="bbo-1s",
            symbols=[symbol],
            stype_in="continuous",
            start=datetime.now(timezone.utc) - timedelta(minutes=2),
        )
        live.start()
        time.sleep(max(2, int(listen_seconds)))
        ok = seen["count"] > 0
        print(f"LIVE {'OK' if ok else 'NO_DATA'} {symbol}: ticks={seen['count']}", flush=True)
        assert ok, f"No live BBO data received for {symbol}"
    except Exception as exc:
        pytest.fail(f"LIVE FAIL {symbol}: {exc}")
    finally:
        if live is not None:
            try:
                live.terminate()
            except Exception:
                pass


def main():
    key = os.getenv("DATABENTO_API_KEY")
    if not key:
        print("FAIL: DATABENTO_API_KEY is not set", flush=True)
        return

    symbols = {
        "XAUUSD": {
            "live": "GC.c.1",
            "historical_candidates": ["GCJ6", "GCM6", "GCZ6", "GC.c.1"],
        },
        "NQ": {
            "live": "NQ.c.1",
            "historical_candidates": ["NQH6", "NQM6", "NQZ6", "NQ.c.1"],
        },
        "EURUSD": {
            "live": "6E.c.1",
            "historical_candidates": ["6EH6", "6EM6", "6EZ6", "6E.c.1"],
        },
        "BTC": {
            "live": "BTC.c.1",
            "historical_candidates": ["BTCH6", "BTCM6", "BTCZ6", "BTC.c.1"],
        },
        "US30": {
            "live": "YM.c.1",
            "historical_candidates": ["YMH6", "YMM6", "YMZ6", "YM.c.1"],
        },
    }
    client = db.Historical(key)

    summary = []
    for canonical, cfg in symbols.items():
        print(f"\n=== {canonical} ===", flush=True)
        hist_ok, hist_symbol = test_historical_bbo(client, cfg["historical_candidates"])
        live_symbol = cfg["live"]
        live_ok = test_live_bbo(key, live_symbol)
        summary.append((canonical, hist_ok, hist_symbol, live_ok, live_symbol))

    print("\n=== SUMMARY ===", flush=True)
    for canonical, hist_ok, hist_symbol, live_ok, live_symbol in summary:
        print(
            f"{canonical}: historical={'OK' if hist_ok else 'FAIL'}"
            f" ({hist_symbol or 'none'}) live={'OK' if live_ok else 'FAIL'} ({live_symbol})",
            flush=True,
        )


if __name__ == "__main__":
    main()
