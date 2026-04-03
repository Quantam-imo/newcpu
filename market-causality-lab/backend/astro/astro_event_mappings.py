"""
Astrology event mappings: planet ingressess, nakshatra transitions → market impacts.
"""

# Planetary ingress event impact mapping
PLANET_IMPACT_MAP = {
    "Sun": {
        "impact_level": "HIGH",
        "market_outcome": "Major trend pivot, seasonal shift, liquidity increase",
        "volatility": "HIGH",
        "expected_direction": "TREND_CHANGE"
    },
    "Moon": {
        "impact_level": "LOW",
        "market_outcome": "Intra-day sentiment flip, noise/choppy action",
        "volatility": "LOW",
        "expected_direction": "MOOD_SHIFT"
    },
    "Mercury": {
        "impact_level": "LOW",
        "market_outcome": "Information processing, quick moves in both directions",
        "volatility": "MEDIUM",
        "expected_direction": "BIDIRECTIONAL"
    },
    "Venus": {
        "impact_level": "LOW",
        "market_outcome": "Demand cycle shift, risk appetite changes",
        "volatility": "LOW",
        "expected_direction": "RISK_ON_OFF"
    },
    "Mars": {
        "impact_level": "MEDIUM",
        "market_outcome": "Volatility spike, aggressive momentum, friction/stops run",
        "volatility": "VERY_HIGH",
        "expected_direction": "SHARP_MOVE"
    },
    "Jupiter": {
        "impact_level": "HIGH",
        "market_outcome": "Expansion phase, optimism wave, breakout push",
        "volatility": "MEDIUM",
        "expected_direction": "TREND_ACCELERATION"
    },
    "Saturn": {
        "impact_level": "HIGH",
        "market_outcome": "Consolidation pressure, resistance testing, structural shift",
        "volatility": "MEDIUM",
        "expected_direction": "TREND_RESISTANCE"
    },
    "Uranus": {
        "impact_level": "MEDIUM",
        "market_outcome": "Sudden reversal, surprise gap, unexpected volatility spike",
        "volatility": "VERY_HIGH",
        "expected_direction": "SHOCK_MOVE"
    },
    "Neptune": {
        "impact_level": "MEDIUM",
        "market_outcome": "Confusion, illusion, fake-outs, trend exhaustion warning",
        "volatility": "LOW",
        "expected_direction": "FALSE_SIGNAL"
    },
    "Pluto": {
        "impact_level": "HIGH",
        "market_outcome": "Regime change, transformation, deep structural shift",
        "volatility": "VERY_HIGH",
        "expected_direction": "PARADIGM_SHIFT"
    },
}

# Nakshatra event mapping
NAKSHATRA_IMPACT_MAP = {
    "impact_level": "MEDIUM",
    "market_outcome": "Mood/sentiment rotation, intra-day character shift, psychological reset",
    "volatility": "MEDIUM",
    "expected_direction": "SENTIMENT_SHIFT"
}


def get_event_type_from_name(event_name: str) -> str:
    """Extract planet or event category from event name."""
    if "ingress" in event_name.lower():
        # e.g. "Sun ingress to Capricorn"
        for planet in PLANET_IMPACT_MAP.keys():
            if planet in event_name:
                return planet
        return "Unknown_Ingress"
    elif "nakshatra" in event_name.lower():
        return "Nakshatra"
    else:
        return "Other"


def get_astro_impact(event_name: str, category: str = "astrology") -> dict:
    """
    Resolve astrological event impact: severity, market outcome, volatility signal.
    
    Returns:
        {
            "event_type": "Sun|Moon|...|Nakshatra",
            "impact_level": "HIGH|MEDIUM|LOW",
            "market_outcome": "descriptive string",
            "volatility_signal": "VERY_HIGH|HIGH|MEDIUM|LOW",
            "expected_direction": "TREND_CHANGE|SHARP_MOVE|MOOD_SHIFT|...",
        }
    """
    event_type = get_event_type_from_name(event_name)

    if event_type == "Nakshatra" or category == "nakshatra":
        base = NAKSHATRA_IMPACT_MAP.copy()
        base["event_type"] = "Nakshatra"
    elif event_type in PLANET_IMPACT_MAP:
        base = PLANET_IMPACT_MAP[event_type].copy()
        base["event_type"] = event_type
    else:
        # Default for unknown events
        base = {
            "event_type": event_type,
            "impact_level": "LOW",
            "market_outcome": f"Minor event: {event_name}",
            "volatility": "LOW",
            "expected_direction": "UNKNOWN"
        }

    return base


def format_astro_display(event_name: str, impact_level: str) -> str:
    """Format astro event for dashboard display."""
    # Shorten long event names for display
    if "ingress" in event_name.lower():
        parts = event_name.split(" ingress ")
        if len(parts) == 2:
            planet = parts[0].strip()
            sign = parts[1].strip()
            return f"{planet[0]}→{sign[:3]}"  # e.g. "S→Cap"
    elif "nakshatra" in event_name.lower():
        parts = event_name.split("enters ")
        if len(parts) == 2:
            nak = parts[1].strip()
            return f"🌙{nak[:4]}"  # e.g. "🌙Revi"
    return event_name[:12]  # Fallback: truncate
