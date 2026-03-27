from fastapi import APIRouter
from astroquant.engine.model_weight_engine import ModelWeightEngine
from astroquant.engine.mentor_engine_v3 import AIMentorV3
from astroquant.engine.consensus_engine import ConsensusEngine

router = APIRouter()

@router.get("/model_weights")
def model_weights():
    # Load model weights and win rates
    mw = ModelWeightEngine()
    mentor = AIMentorV3()
    # Example model names (should match those used in mentor/consensus)
    model_names = [
        "MentorICTEngine", "MentorGannEngine", "MentorAstroEngine", "MentorNewsEngine",
        "MentorLiquidityEngine", "MentorInstitutionEngine", "MentorProbabilityEngine"
    ]
    weights = {name: mw.model_weight(name) for name in model_names}
    win_rates = {name: mw.win_rate(name) for name in model_names}
    # Simulate votes (in production, collect from consensus/mentor)
    dummy_market = {"price": 2000, "prev_low": 1990, "prev_high": 2010}
    mentor_out = mentor.generate(dummy_market)
    votes = {
        "ICT": mentor_out["ict"],
        "Gann": mentor_out["gann"],
        "Astro": mentor_out["astro"],
        "News": mentor_out["news"],
        "Liquidity": mentor_out["liquidity"],
        "Institution": mentor_out["institution"],
        "Probability": mentor_out["probability"]
    }
    # Ensemble consensus (weighted)
    # For demonstration, use only ICT, Gann, Astro, News as base models
    from astroquant.engine.mentor_ict_engine import MentorICTEngine
    from astroquant.engine.mentor_gann_engine import MentorGannEngine
    from astroquant.engine.mentor_astro_engine import MentorAstroEngine
    from astroquant.engine.mentor_news_engine import MentorNewsEngine
    base_models = [MentorICTEngine(), MentorGannEngine(), MentorAstroEngine(), MentorNewsEngine()]
    consensus = ConsensusEngine(base_models, model_weight_engine=mw)
    consensus_signal = consensus.get_consensus_signal(dummy_market)
    diagnostics = {
        "model_weights": weights,
        "win_rates": win_rates,
        "votes": votes,
        "ensemble_decision": consensus_signal
    }
    return diagnostics