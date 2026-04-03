import pandas as pd

from astroquant.advanced.backtest_runner import _jd_from_bar, _resolve_trade_direction


def test_jd_from_bar_prefers_datetime_column_over_index():
    # Non-datetime index should not prevent using explicit bar datetime.
    df = pd.DataFrame(
        {
            "datetime": ["2026-04-03T12:00:00Z", "2026-04-03T13:00:00Z"],
            "open": [1.0, 1.1],
            "high": [1.2, 1.3],
            "low": [0.9, 1.0],
            "close": [1.1, 1.2],
        },
        index=[0, 1],
    )

    jd = _jd_from_bar(df, 1)
    assert jd is not None


def test_resolve_trade_direction_avoids_default_buy_on_neutral():
    # Neutral Gann + no ICT direction + neutral astro should not force BUY.
    direction = _resolve_trade_direction(0.0, "NO_TRADE", 0)
    assert direction is None


def test_resolve_trade_direction_falls_back_to_ict_then_astro():
    assert _resolve_trade_direction(0.0, "BUY", 0) == "BUY"
    assert _resolve_trade_direction(0.0, "NO_TRADE", -1) == "SELL"
