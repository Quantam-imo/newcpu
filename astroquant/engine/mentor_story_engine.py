from __future__ import annotations


class MentorStoryEngine:
    def build(self, context: dict, liq: dict, inst: dict, ict: dict, gann: dict, astro: dict, news: dict, session: dict) -> str:
        return (
            f"Current price: {context.get('price', '--')}\n\n"
            f"Session: {session.get('session', '--')} — {session.get('phase', '--')} phase.\n\n"
            f"Institutional activity shows delta {inst.get('delta', '--')}.\n\n"
            f"Iceberg buyers: {inst.get('iceberg_buy', '--')}\n"
            f"Iceberg sellers: {inst.get('iceberg_sell', '--')}\n\n"
            f"Liquidity target sits near {liq.get('external_high', '--')}.\n\n"
            f"ICT pattern detected: {ict.get('turtle_soup', '--')}.\n\n"
            f"Gann cycle at {gann.get('cycle', '--')} bars.\n\n"
            f"Astro timing window active: {astro.get('planet_event', '--')}.\n\n"
            f"Upcoming news: {news.get('next_event', '--')} at {news.get('time', '--')}.\n\n"
            "Expected delivery direction forming toward liquidity."
        )
