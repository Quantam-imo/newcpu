from __future__ import annotations

from .mentor_context_engine import MentorContextEngine
from .mentor_liquidity_engine import MentorLiquidityEngine
from .mentor_institution_engine import MentorInstitutionEngine
from .mentor_ict_engine import MentorICTEngine
from .mentor_gann_engine import MentorGannEngine
from .mentor_astro_engine import MentorAstroEngine
from .mentor_news_engine import MentorNewsEngine
from .mentor_probability_engine import MentorProbabilityEngine
from .mentor_story_engine import MentorStoryEngine
from .mentor_session_engine import MentorSessionEngine


class AIMentorV3:
    def __init__(self):
        self.context = MentorContextEngine()
        self.liquidity = MentorLiquidityEngine()
        self.institution = MentorInstitutionEngine()
        self.ict = MentorICTEngine()
        self.gann = MentorGannEngine()
        self.astro = MentorAstroEngine()
        self.news = MentorNewsEngine()
        self.session = MentorSessionEngine()
        self.probability = MentorProbabilityEngine()
        self.story = MentorStoryEngine()

    def generate(self, market: dict) -> dict:
        context = self.context.analyze(market)
        liquidity = self.liquidity.analyze(market)
        institution = self.institution.analyze(market)
        ict = self.ict.detect(market)
        gann = self.gann.calculate(market)
        astro = self.astro.calculate(market)
        news = self.news.check(market)
        session = self.session.analyze(market)
        probability = self.probability.score(context, liquidity, institution, ict, gann, astro, news)
        story = self.story.build(context, liquidity, institution, ict, gann, astro, news, session)
        return {
            "context": context,
            "liquidity": liquidity,
            "institution": institution,
            "ict": ict,
            "gann": gann,
            "astro": astro,
            "news": news,
            "session": session,
            "probability": probability,
            "story": story,
        }
