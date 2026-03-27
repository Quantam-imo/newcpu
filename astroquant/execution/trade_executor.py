def execute_signal(signal):

# --- PlaywrightExecution integration ---
from execution.playwright_engine import PlaywrightExecution

engine = None

def initialize_engine(page, state_manager, logger):
    global engine
    engine = PlaywrightExecution(page, state_manager, logger)
    return engine

def execute_signal(signal, lot=0.01):
    if engine is None:
        raise RuntimeError("PlaywrightExecution engine not initialized")
    position = engine.state.position
    if signal == "BUY" and position != "BUY":
        return engine.place_trade("BUY", lot)
    elif signal == "SELL" and position != "SELL":
        return engine.place_trade("SELL", lot)
    return "NO_ACTION"


def safe_execute(signal, confidence, lot=0.01):
    if confidence < 0.7:
        print("Low confidence — skip")
        return "SKIPPED"
    return execute_signal(signal, lot)

# Example trade management usage:
# engine._configure_protection(engine.page, {"sl": entry-10, "tp": entry+20})
