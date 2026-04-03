"""
Astrology event narration and impact prediction.
Generates descriptive narrations for astrological events and predicts market behavior.
"""


# Event-specific narrations for market behavior predictions
ASTRO_NARRATIONS = {
    "Sun ingress": {
        "description": "Seasonal pivot point. Market shifts trend direction or accelerates existing trend.",
        "gann_alignment": "Watch for P=T (price move = days passed) and P=D (price degrees = calendar degrees)",
        "numerology_impact": "Date numerology + price numerology should align; major shifts often happen at 9-cycle endings",
        "structure_watch": "Major structure breakout or reversal; look for BOS (Break of Structure) on higher timeframe",
        "market_physics": "Liquidity surge + momentum acceleration; velocity doubles; volatility rises sharply",
        "news_trigger": "Economic announcements, sentiment shifts, major economic data releases expected",
        "price_levels": "Previous swing highs/lows become key support/resistance",
        "duration": "3-7 days primary impact, 21+ days secondary waves",
    },
    "Saturn ingress": {
        "description": "Structural testing and resistance. Market consolidates, tests support/resistance heavily.",
        "gann_alignment": "P=D (price degrees) often tested at exact gann angles; watch 45°, 90°, 180° angles",
        "numerology_impact": "Completion cycles; major numerological milestones trigger reversals",
        "structure_watch": "Multiple rejections at previous highs; accumulation patterns; CHoCH (Change of Character)",
        "market_physics": "Velocity decelerates; momentum wanes; structure becomes apparent; price clusters around levels",
        "news_trigger": "Fed decisions, interest rate concerns, stability questions, structural market reassessment",
        "price_levels": "Market gets squeezed between key resistance and support; narrow range develops",
        "duration": "7-21 days primary consolidation, can resolve with sharp breakout",
    },
    "Mars ingress": {
        "description": "Aggressive volatility spike. Sharp moves in both directions, stops get run, trend accelerates violently.",
        "gann_alignment": "Rapid P=T equality breaches; fast moves break gann angles; multiple angle crossings in short time",
        "numerology_impact": "Chaotic numerology; disharmony; cycles don't align; unpredictable behavior",
        "structure_watch": "Liquidity sweeps, stop hunts, false breakouts, LL/HH patterns distorted, whipsaws expected",
        "market_physics": "Highest velocity period; acceleration extreme; volatility bands widen sharply; momentum whips",
        "news_trigger": "Geopolitical surprises, unexpected economic data, central bank shocks, risk-off events",
        "price_levels": "Multiple levels tested rapidly; no single holding level; ranges collapse",
        "duration": "24-72 hours acute volatility spike; secondary waves for 2+ weeks",
    },
    "Jupiter ingress": {
        "description": "Expansion and optimism waves. Markets break out, rallies extend, bull run acceleration.",
        "gann_alignment": "P=T equality maintained over extended period; price climbs gann fan lines; degree angles support uptrend",
        "numerology_impact": "Harmonious numerology; cycles align; 3-6-9 patterns common; smooth price progression",
        "structure_watch": "Clean HH/HL patterns; BOS to upside; supply levels get cleared; new all-time moves",
        "market_physics": "Sustained high velocity; momentum persists; liquidity supports moves; few pullbacks",
        "news_trigger": "Positive economic data, risk-on sentiment, central bank easing, growth expectations",
        "price_levels": "Previous resistance becomes new support; market makers push higher; new structure forms",
        "duration": "10-30 days primary expansion; 3+ month secondary bull wave",
    },
    "Uranus ingress": {
        "description": "Sudden shock and reversal. Unexpected gap moves, surprise reversals, paradigm shift.",
        "gann_alignment": "P=T/D equations break suddenly; gann angles get exceeded; no warning, sharp reversal",
        "numerology_impact": "Numerology suddenly shifts; cycle inversion; 180° turn; disharmonious to harmonious or vice versa",
        "structure_watch": "Sudden BOS both directions; gaps open without reason; FVG (Fair Value Gaps); sweep and reverse",
        "market_physics": "Sudden velocity spike then collapse; momentum reverses instantly; slack in order flow appears",
        "news_trigger": "Surprise data, unexpected policy shifts, black swan events, hidden information revealed",
        "price_levels": "Old support/resistance suddenly broken; new levels established overnight",
        "duration": "Shock is 1-2 hours; recovery/retest 3-5 days",
    },
    "Neptune ingress": {
        "description": "Illusion and confusion. Fake-outs, false signals, trend exhaustion warnings, deception.",
        "gann_alignment": "P=T appears true but breaks; gann angles seem to hold then fail; false convergences",
        "numerology_impact": "Numerology misaligns with price action; calculations suggest one thing, market does another",
        "structure_watch": "False breakouts, bear traps, bull traps, fake structures, pattern failures common",
        "market_physics": "Velocity appears strong but reverses; momentum looks real but disappears; illusion of trend",
        "news_trigger": "Contradicting data, unclear guidance, mixed messages, speculation vs reality",
        "price_levels": "Levels seem to hold then break; no true support/resistance; whipsaw levels",
        "duration": "Entire event period is confusion; resolution comes with clearer data",
    },
    "Moon ingress": {
        "description": "Intra-day sentiment rotation. Daily mood swings, psychological resets, fast micro-reversals.",
        "gann_alignment": "Micro P=T equalities; small hour/minute angles active; fast cycling through gann time periods",
        "numerology_impact": "Hour numerology matters; specific times have psychological influence; 3-hour cycles common",
        "structure_watch": "Micro structures (15m-1h); daily FVG; small BOS patterns; intra-day reversal points",
        "market_physics": "High frequency oscillation; momentum changes every 3-6 bars; volatility within tight bands",
        "news_trigger": "Intra-day economic releases, sentiment headlines, retail flow changes, option expirations",
        "price_levels": "Tight range; multiple rejections of same levels; small 5-20 pip ranges, then 50-100 pip breakout",
        "duration": "4-12 hours; resets with next session open",
    },
    "Mercury ingress": {
        "description": "Information processing. Bidirectional moves, quick reversals on news, confusion then clarity.",
        "gann_alignment": "P=T alternates; both up and down moves show equal time/price; zigzag pattern",
        "numerology_impact": "Number vibration splits; dual nature; 2,5 prominent; symmetry in price/time moves",
        "structure_watch": "Double tops/bottoms, IchimokuClouds twist, volatility bands squeeze then expand",
        "market_physics": "Oscillating velocity; momentum swings both ways; multiple direction changes per day",
        "news_trigger": "Data releases with reversals, earnings calls, Fed speeches, economic calendar",
        "price_levels": "Levels tested from both sides; round numbers become battle zones; tug-of-war patterns",
        "duration": "6-18 hours; reverses with new news",
    },
    "Venus ingress": {
        "description": "Risk appetite shift. Demand cycles rotate, correlations change, risk-on/off toggle.",
        "gann_alignment": "P=D angles shift; previous angles lose power; new angles take over",
        "numerology_impact": "Harmonious cycles continue; similar to previous cycle but with offset",
        "structure_watch": "Character change; structure becomes better/worse; quality of price action shifts",
        "market_physics": "Velocity changes sustainably but moderately; momentum qualitatively shifts (strong→weak or vice)",
        "news_trigger": "Risk sentiment flip, central bank tone, equity market direction change, breadth shifts",
        "price_levels": "Previous levels re-tested after setup change; old support becomes new resistance",
        "duration": "2-5 days for initial shift; 10+ days for sustained new character",
    },
    "Pluto ingress": {
        "description": "Paradigm shift and regime change. Deep structural transformation, market character fundamentally changes.",
        "gann_alignment": "Historical gann angles become invalid; new angles emerge; degree calculations recalibrate",
        "numerology_impact": "Root number cycle completes and resets; 9→1 transition; complete renewal",
        "structure_watch": "Massive structure change; old timeframe structures invalidate; new framework emerges",
        "market_physics": "Fundamental volatility/momentum character changes; regime shift in velocity patterns",
        "news_trigger": "Policy paradigm shift, market structure changes, new era begins (post-crisis, post-war, new system)",
        "price_levels": "All historical levels become irrelevant; new support/resistance zones establish from scratch",
        "duration": "3-30 days to establish new regime; 3+ months to complete transformation",
    },
    "Nakshatra transition": {
        "description": "Psychological mood rotation. Daily character and sentiment shift, intra-day character change.",
        "gann_alignment": "Micro-time cycles shift; hourly angles become more/less relevant",
        "numerology_impact": "Lunar day numerology shifts; 27-cycle resets; new character begins",
        "structure_watch": "Intra-day character change; quality of movement shifts; volatility profile changes per hour",
        "market_physics": "Intra-day volatility profile changes; velocity oscillation pattern shifts",
        "news_trigger": "Sentiment headlines, retail flow changes, options expirations, session openings",
        "price_levels": "Daily levels tested; new intra-day ranges establish",
        "duration": "24 hours (full lunar day); resets with next nakshatra entry",
    },
}


def generate_astro_narration(event_name: str, category: str = "astrology") -> dict:
    """
    Generate detailed narration for an astrology event.
    
    Returns:
        {
            "narration": "Full descriptive text",
            "gann_prediction": "What gann patterns to watch",
            "numerology_alignment": "How numerology relates",
            "structure_outlook": "Market structure expectations",
            "physics_expectation": "Market physics (velocity, momentum)",
            "news_setup": "Likely news triggers",
            "price_targets": "Key levels to watch",
            "duration": "Event duration",
        }
    """
    event_type = None
    
    # Extract event type from name
    for key in ASTRO_NARRATIONS.keys():
        if key.lower() in event_name.lower():
            event_type = key
            break
    
    if not event_type:
        # Default for unknown events
        return {
            "narration": f"Minor astrological event: {event_name}",
            "gann_prediction": "Monitor P=T and P=D relationships",
            "numerology_alignment": "Check if price and date numerology align",
            "structure_outlook": "Possible minor structure shift",
            "physics_expectation": "Normal volatility and velocity",
            "news_setup": "May trigger minor news reactions",
            "price_targets": "Test key support/resistance levels",
            "duration": "1-3 days",
        }
    
    details = ASTRO_NARRATIONS[event_type]
    
    return {
        "narration": details["description"],
        "gann_prediction": details["gann_alignment"],
        "numerology_alignment": details["numerology_impact"],
        "structure_outlook": details["structure_watch"],
        "physics_expectation": details["market_physics"],
        "news_setup": details["news_trigger"],
        "price_targets": details["price_levels"],
        "duration": details["duration"],
    }


def format_astro_event_briefing(event_name: str, impact_level: str, time_delta_hours: float, market_outcome: str) -> str:
    """
    Format a complete astrology event briefing for the AI to analyze.
    
    Returns a multi-line briefing string with all context needed for trading.
    """
    narration = generate_astro_narration(event_name)
    
    time_phrase = ""
    if time_delta_hours < 0.5:
        time_phrase = f"NOW (imminent within {int(time_delta_hours * 60)} minutes)"
    elif time_delta_hours < 0:
        time_phrase = f"ACTIVE (occurred {abs(time_delta_hours):.1f}h ago)"
    else:
        time_phrase = f"{time_delta_hours:.1f} hours ahead"
    
    briefing = f"""
╔════════════════════════════════════════════════════════════════════╗
║                    🌙 ASTROLOGY EVENT BRIEFING                    ║
╠════════════════════════════════════════════════════════════════════╣
║ Event: {event_name:60s} ║
║ Impact: {impact_level:11s} | Timing: {time_phrase:47s} ║
║ Outcome: {market_outcome:60s} ║
╠════════════════════════════════════════════════════════════════════╣
║ MARKET NARRATIVE:
║ {narration['narration']}
║
║ GANN ANALYSIS TO WATCH:
║ {narration['gann_prediction']}
║
║ NUMEROLOGY ALIGNMENTS:
║ {narration['numerology_alignment']}
║
║ MARKET STRUCTURE EXPECTATIONS:
║ {narration['structure_outlook']}
║
║ MARKET PHYSICS (Velocity & Momentum):
║ {narration['physics_expectation']}
║
║ LIKELY NEWS TRIGGERS:
║ {narration['news_setup']}
║
║ KEY PRICE LEVELS TO WATCH:
║ {narration['price_targets']}
║
║ EVENT DURATION: {narration['duration']}
╚════════════════════════════════════════════════════════════════════╝
"""
    return briefing
