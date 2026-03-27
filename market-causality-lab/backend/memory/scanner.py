from backend.core.state_engine import build_state
from backend.physics.physics_engine import physics_engine
from backend.gann.gann_engine import gann_engine
from backend.engines.liquidity_engine import liquidity_engine
from backend.engines.phase_engine import phase_engine
from backend.sync.sync_engine import sync_engine


def _extract_news_context(sub_df):
    if sub_df.empty:
        return {
            "event_active": False,
            "event_count": 0,
            "high_impact_active": False,
            "impact_score": 0,
        }

    last_row = sub_df.iloc[-1]
    event_count = int(last_row.get("news_event_count", 0) or 0)
    high_impact_count = int(last_row.get("news_high_impact_count", 0) or 0)
    impact_score = int(last_row.get("news_impact_score", 0) or 0)

    return {
        "event_active": bool(last_row.get("news_event_active", False)),
        "event_count": event_count,
        "high_impact_active": high_impact_count > 0,
        "impact_score": impact_score,
    }


def scan_market(df):
    memory = []

    # Start after enough data; fallback for shorter datasets.
    start_idx = 50 if len(df) > 50 else 10

    for i in range(start_idx, len(df)):
        sub_df = df.iloc[:i]

        state = build_state(sub_df)

        physics = physics_engine(state)
        gann = gann_engine(state)
        liquidity = liquidity_engine(sub_df)
        phase = phase_engine(state, liquidity)
        signal = sync_engine(state, physics, gann, liquidity, phase)
        news = _extract_news_context(sub_df)

        record = {
            "state": state,
            "physics": physics,
            "gann": gann,
            "liquidity": liquidity,
            "phase": phase,
            "signal": signal,
            "news": news,
        }

        memory.append(record)

    return memory