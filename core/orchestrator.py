from astroquant.engine.mentor_engine_v3 import AIMentorV3
from astroquant.ai.trade_db import init_db
from astroquant.ai.trade_logger import log_trade
from astroquant.ai.risk_model import calculate_lot
from astroquant.ai.execution_model import optimize_entry
from astroquant.engine.ict_engine import detect_structure
from astroquant.engine.ict_engine_pro import get_htf_bias

# Example: This orchestrator fuses all mentor/AI/engine logic for a single decision cycle

def run_cycle(df, htf_df, ltf_df, price, balance=50000, risk_percent=1.0):
    # 1. Initialize DB (idempotent)
    init_db()

    # 2. Prepare market dict for mentor engines
    market = {
        "symbol": "GC",
        "price": price,
        "prev_low": df["low"].iloc[-2],
        "prev_high": df["high"].iloc[-2],
        "htf_bias": get_htf_bias(htf_df),  # Dynamic HTF bias from ICT engine
        "ltf_structure": detect_structure(df),  # Dynamic LTF structure from ICT engine
        # ...add more features as needed
    }

    mentor = AIMentorV3()
    mentor_out = mentor.generate(market)

    # 3. Use probability verdict for action
    action = "NO_TRADE"
    if mentor_out["probability"]["verdict"].startswith("High"):
        action = "BUY"
    elif mentor_out["probability"]["verdict"].startswith("Moderate"):
        action = "SELL"

    # 4. Risk model for lot size
    sl_points = 20  # Example, should be dynamic
    lot = calculate_lot(balance, risk_percent, sl_points)

    # 5. Optimize entry
    entry_data = optimize_entry({"action": action, "sl": price-20, "tp": price+60}, price)

    # 6. Log trade if action
    if action != "NO_TRADE":
        log_trade(action, entry_data["entry"], entry_data["sl"], entry_data["tp"])

    return {
        "action": action,
        "entry": entry_data["entry"],
        "sl": entry_data["sl"],
        "tp": entry_data["tp"],
        "mentor": mentor_out
    }
