from astroquant.ai.llm_engine import get_llm_trade
from astroquant.ai.strategy_model import strategy_score

def final_decision(ict, gann, astro, price):
    # Strategy scoring
    strat = strategy_score(ict, gann, astro)

    context = {
        "ict": ict,
        "gann": gann,
        "astro": astro,
        "price": price,
        "confidence": strat["confidence"]
    }

    # LLM decision
    llm = get_llm_trade(context)

    return llm
