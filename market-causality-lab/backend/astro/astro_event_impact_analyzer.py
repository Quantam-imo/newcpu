"""
Astrology event impact analyzer.
Analyzes Gann, Numerology, Market Structure, and Physics at event times.
Generates AI learning patterns from astro event market reactions.
"""

from __future__ import annotations

import math
import pandas as pd
from datetime import datetime, timedelta


def analyze_gann_at_event(df: pd.DataFrame, event_time: pd.Timestamp) -> dict:
    """
    Analyze Gann relationships at event time.
    Check for P=T (price=time), P=D (price=degrees), Date=Price alignments.
    """
    if df.empty:
        return {
            "p_equals_t": False,
            "p_equals_degree": False,
            "date_equals_price": False,
            "current_degree": 0.0,
            "bar_since_event": 0,
            "gann_angle_proximity": "NONE",
        }
    
    current_bar = df.iloc[-1]
    price = float(current_bar["close"])
    
    # Calculate Gann degree (price-based angle)
    gann_degree = (math.sqrt(price) * 180) % 360
    
    # Get event time bar if exists
    event_df = df[df["time"] == event_time] if "time" in df.columns else None
    bars_since_event = 0
    
    if "time" in df.columns:
        time_diffs = (df["time"] - event_time).abs()
        if not time_diffs.empty:
            bars_since_event = int(time_diffs.idxmin())
    
    # Check P=T: price move should equal bar count
    if len(df) >= 10:
        price_move = float(abs(df["close"].iloc[-1] - df["close"].iloc[-10]))
        time_move = 10
        p_equals_t = abs(price_move - time_move) < 0.5
    else:
        p_equals_t = False
    
    # Check key Gann angles: 45°, 90°, 180°, 225°
    key_angles = [45, 90, 180, 225, 315]
    closest_angle = min(key_angles, key=lambda a: min(abs(gann_degree - a), 360 - abs(gann_degree - a)))
    angle_proximity = "EXACT" if abs(gann_degree - closest_angle) < 5 or abs(gann_degree - closest_angle) > 355 else "NEAR" if abs(gann_degree - closest_angle) < 15 else "NONE"
    
    return {
        "p_equals_t": p_equals_t,
        "p_equals_degree": abs(price - gann_degree) < 10,  # Close proximity
        "date_equals_price": False,  # TODO: implement date numerology = price match
        "current_degree": round(gann_degree, 2),
        "nearest_key_angle": closest_angle,
        "bars_since_event": bars_since_event,
        "gann_angle_proximity": angle_proximity,
    }


def analyze_numerology_at_event(df: pd.DataFrame, event_time: pd.Timestamp, event_name: str) -> dict:
    """
    Analyze numerology alignments at event time.
    Check if price numerology matches date numerology and event numerology.
    """
    def reduce_to_single_digit(n):
        while n > 9:
            n = sum(int(d) for d in str(n))
        return n
    
    if df.empty or not isinstance(event_time, pd.Timestamp):
        return {
            "event_numerology": 0,
            "price_numerology": 0,
            "date_numerology": 0,
            "harmonious_alignment": False,
            "numerology_cycle": "UNKNOWN",
        }
    
    # Event numerology from event_name
    event_num_sum = sum(int(d) for d in str(len(event_name)) + str(event_time.month) + str(event_time.day))
    event_num = reduce_to_single_digit(event_num_sum)
    
    # Current price numerology
    current_price = int(df["close"].iloc[-1])
    price_num = reduce_to_single_digit(sum(int(d) for d in str(current_price)))
    
    # Current date numerology
    today = event_time.day + event_time.month + event_time.year
    date_num = reduce_to_single_digit(today)
    
    # Check alignments
    harmonious = (event_num == price_num) or (price_num == date_num) or ((event_num + price_num) % 9 == 0)
    
    # Determine cycle phase
    if event_num in [1, 2, 3]:
        cycle = "EXPANSION"
    elif event_num in [4, 5, 6]:
        cycle = "CONSOLIDATION"
    elif event_num in [7, 8, 9]:
        cycle = "COMPLETION"
    else:
        cycle = "NEUTRAL"
    
    return {
        "event_numerology": event_num,
        "price_numerology": price_num,
        "date_numerology": date_num,
        "harmonious_alignment": harmonious,
        "numerology_description": f"Event#{event_num} × Price#{price_num} × Date#{date_num}",
        "numerology_cycle": cycle,
    }


def analyze_market_structure_at_event(df: pd.DataFrame, event_time: pd.Timestamp) -> dict:
    """
    Analyze market structure (major/minor) at event time.
    Detect HH/HL (higher highs/lows), LL/LH patterns, BOS (break of structure).
    """
    if len(df) < 20:
        return {
            "structure_type": "INSUFFICIENT_DATA",
            "higher_highs": False,
            "higher_lows": False,
            "lower_lows": False,
            "lower_highs": False,
            "bos_confirmed": False,
            "major_structure": "UNKNOWN",
        }
    
    recent_df = df.tail(20).copy()
    highs = recent_df["high"].values
    lows = recent_df["low"].values
    closes = recent_df["close"].values
    
    # Check for HH and HL patterns (uptrend structure)
    recent_high = highs[-1]
    prev_high = max(highs[:-1])
    recent_low = lows[-1]
    prev_low = min(lows[:-1])
    
    higher_highs = recent_high > prev_high
    higher_lows = recent_low > min(lows[:-5])  # Compare to earlier lows
    lower_lows = recent_low < prev_low
    lower_highs = recent_high < max(highs[:-5])
    
    # BOS (Break of Structure) confirmation
    bos_confirmed = (higher_highs and higher_lows) or (lower_lows and lower_highs)
    
    # Major structure determination
    if higher_highs and higher_lows:
        major_struct = "UPTREND_BUILDING"
    elif lower_lows and lower_highs:
        major_struct = "DOWNTREND_BUILDING"
    elif bos_confirmed:
        major_struct = "BOS_CONFIRMED"
    else:
        major_struct = "CONSOLIDATION"
    
    return {
        "structure_type": major_struct,
        "higher_highs": higher_highs,
        "higher_lows": higher_lows,
        "lower_lows": lower_lows,
        "lower_highs": lower_highs,
        "bos_confirmed": bos_confirmed,
        "major_structure": major_struct,
    }


def analyze_market_physics_at_event(df: pd.DataFrame, event_time: pd.Timestamp) -> dict:
    """
    Analyze market physics: velocity (price per bar), momentum, volatility.
    Detect if event correlates with physics changes.
    """
    if len(df) < 5:
        return {
            "current_velocity": 0.0,
            "momentum_direction": "NEUTRAL",
            "volatility_level": "LOW",
            "price_acceleration": 0.0,
        }
    
    recent = df.tail(10).copy()
    closes = recent["close"].values
    
    # Velocity: average price change per bar
    price_changes = [abs(closes[i] - closes[i-1]) for i in range(1, len(closes))]
    current_velocity = price_changes[-1] if len(price_changes) > 0 else 0.0
    avg_velocity = sum(price_changes) / len(price_changes) if price_changes else 0.0
    
    # Momentum: direction of recent moves
    momentum_sum = 0
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            momentum_sum += 1
        else:
            momentum_sum -= 1
    
    if momentum_sum > 3:
        momentum = "STRONG_UP"
    elif momentum_sum > 1:
        momentum = "MILD_UP"
    elif momentum_sum < -3:
        momentum = "STRONG_DOWN"
    elif momentum_sum < -1:
        momentum = "MILD_DOWN"
    else:
        momentum = "NEUTRAL"
    
    # Volatility: standard deviation of changes
    if len(price_changes) > 1:
        mean_change = sum(price_changes) / len(price_changes)
        variance = sum((x - mean_change) ** 2 for x in price_changes) / len(price_changes)
        volatility = variance ** 0.5
        
        if volatility > avg_velocity * 2:
            vol_level = "VERY_HIGH"
        elif volatility > avg_velocity * 1.5:
            vol_level = "HIGH"
        elif volatility > avg_velocity * 0.8:
            vol_level = "NORMAL"
        else:
            vol_level = "LOW"
    else:
        vol_level = "UNKNOWN"
    
    # Acceleration: is velocity increasing or decreasing
    acceleration = current_velocity - (avg_velocity if len(price_changes) > 0 else 0)
    
    return {
        "current_velocity": round(current_velocity, 6),
        "average_velocity": round(avg_velocity, 6),
        "momentum_direction": momentum,
        "volatility_level": vol_level,
        "price_acceleration": round(acceleration, 6),
    }


def analyze_astro_event_impact(
    df: pd.DataFrame,
    event_name: str,
    event_time: pd.Timestamp,
    impact_level: str,
    market_outcome: str,
) -> dict:
    """
    Comprehensive analysis of astrology event impact on market.
    Combines Gann, Numerology, Market Structure, and Market Physics.
    
    Returns:
        {
            "gann_analysis": {...},
            "numerology_analysis": {...},
            "structure_analysis": {...},
            "physics_analysis": {...},
            "event_impact_summary": {
                "high_probability_outcome": str,
                "gann_convergence_strength": "STRONG"|"MODERATE"|"WEAK",
                "numerology_harmony": "ALIGNED"|"MIXED"|"MISALIGNED",
                "structure_setup": "IDEAL"|"GOOD"|"NEUTRAL"|"POOR",
                "physics_expectation": "MATCHES_PREDICTION"|"UNCERTAIN"|"CONTRADICTS_PREDICTION",
                "ai_confidence": float (0-1),
                "next_24h_outlook": str,
            }
        }
    """
    gann_analysis = analyze_gann_at_event(df, event_time)
    numerology_analysis = analyze_numerology_at_event(df, event_time, event_name)
    structure_analysis = analyze_market_structure_at_event(df, event_time)
    physics_analysis = analyze_market_physics_at_event(df, event_time)
    
    # Synthesize impact
    gann_strength = "STRONG" if gann_analysis["gann_angle_proximity"] == "EXACT" and gann_analysis["p_equals_t"] else "MODERATE" if gann_analysis["gann_angle_proximity"] in ["NEAR", "EXACT"] else "WEAK"
    
    numerology_harmony = "ALIGNED" if numerology_analysis["harmonious_alignment"] else "MIXED" if abs(numerology_analysis["event_numerology"] - numerology_analysis["price_numerology"]) <= 2 else "MISALIGNED"
    
    structure_setup = "IDEAL" if structure_analysis["bos_confirmed"] else "GOOD" if structure_analysis["major_structure"] in ["UPTREND_BUILDING", "DOWNTREND_BUILDING"] else "NEUTRAL" if structure_analysis["major_structure"] == "CONSOLIDATION" else "POOR"
    
    physics_match = "MATCHES_PREDICTION" if physics_analysis["volatility_level"] in ["HIGH", "VERY_HIGH"] and impact_level in ["HIGH", "MEDIUM"] else "UNCERTAIN"
    
    # Calculate AI confidence (0-1)
    confidence_score = 0.0
    if gann_analysis["gann_angle_proximity"] == "EXACT":
        confidence_score += 0.25
    elif gann_analysis["gann_angle_proximity"] == "NEAR":
        confidence_score += 0.15
    
    if numerology_analysis["harmonious_alignment"]:
        confidence_score += 0.20
    else:
        confidence_score += 0.05
    
    if structure_analysis["bos_confirmed"]:
        confidence_score += 0.25
    elif structure_analysis["major_structure"] in ["UPTREND_BUILDING", "DOWNTREND_BUILDING"]:
        confidence_score += 0.15
    
    if physics_analysis["volatility_level"] in ["HIGH", "VERY_HIGH"]:
        confidence_score += 0.15
    else:
        confidence_score += 0.05
    
    confidence_score = min(confidence_score, 1.0)
    
    return {
        "gann_analysis": gann_analysis,
        "numerology_analysis": numerology_analysis,
        "structure_analysis": structure_analysis,
        "physics_analysis": physics_analysis,
        "event_impact_summary": {
            "event_name": event_name,
            "impact_level": impact_level,
            "market_outcome_predicted": market_outcome,
            "gann_convergence_strength": gann_strength,
            "numerology_harmony": numerology_harmony,
            "structure_setup_quality": structure_setup,
            "physics_expectation": physics_match,
            "ai_confidence_score": round(confidence_score, 3),
            "next_24h_outlook": f"{impact_level} impact event with {numerology_harmony} numerology and {structure_setup} structure setup",
        }
    }
