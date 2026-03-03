from engine.ai_governance_engine import AIGovernanceEngine


_shared_governance_engine = None


def get_governance_engine():
    global _shared_governance_engine
    if _shared_governance_engine is None:
        _shared_governance_engine = AIGovernanceEngine()
    return _shared_governance_engine
