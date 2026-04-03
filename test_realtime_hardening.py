from types import SimpleNamespace

from astroquant.advanced.realtime_runner import _env_int
from astroquant.advanced.realtime_data_engine import RealTimeDataEngine, FeedConfig


def test_env_int_fallback_and_bounds(monkeypatch):
    monkeypatch.setenv("AQ_TEST_INT", "not-an-int")
    assert _env_int("AQ_TEST_INT", 10, minimum=1, maximum=20) == 10

    monkeypatch.setenv("AQ_TEST_INT", "999")
    assert _env_int("AQ_TEST_INT", 10, minimum=1, maximum=20) == 20

    monkeypatch.setenv("AQ_TEST_INT", "0")
    assert _env_int("AQ_TEST_INT", 10, minimum=1, maximum=20) == 1


def test_realtime_engine_clamps_feed_config():
    cfg = FeedConfig(lookback_minutes=-50, poll_seconds=0)
    engine = RealTimeDataEngine(api_key="dummy", feed_config=cfg)

    assert engine.cfg.lookback_minutes >= 1
    assert engine.cfg.poll_seconds >= 1


def test_compute_snapshot_handles_feed_failure(monkeypatch):
    engine = RealTimeDataEngine(api_key="dummy", feed_config=FeedConfig())

    def _boom(*args, **kwargs):
        raise RuntimeError("feed failed")

    monkeypatch.setattr(engine, "fetch_recent_candles", _boom)

    snap = engine.compute_snapshot()
    assert snap["status"] == "UNAVAILABLE"
    assert snap["signal"] == "NO TRADE"
    assert snap["diagnostics"]["reason"] == "FEED_FETCH_FAILED"


def test_run_forever_survives_callback_exception(monkeypatch):
    engine = RealTimeDataEngine(api_key="dummy", feed_config=FeedConfig(poll_seconds=1))

    monkeypatch.setattr(engine, "compute_snapshot", lambda: {"status": "OK"})
    monkeypatch.setattr("astroquant.advanced.realtime_data_engine.time.sleep", lambda _s: None)

    calls = {"n": 0}

    def _bad_callback(_snapshot):
        calls["n"] += 1
        raise RuntimeError("callback failed")

    # Should exit by max_iterations without propagating callback failure.
    engine.run_forever(on_signal=_bad_callback, max_iterations=2)
    assert calls["n"] == 2
