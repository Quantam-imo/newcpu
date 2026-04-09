#!/usr/bin/env python3
"""
Comprehensive Test Suite for AstroQuant
Tests all major components: ICT, GANN, Astrology, AI Mentor, and Dashboard panels
"""

import json
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

# Test data
SAMPLE_CANDLES = [
    {"open": 2040.5, "high": 2045.0, "low": 2039.5, "close": 2042.0, "volume": 1000, "timestamp": "2026-03-22T10:00:00Z"},
    {"open": 2042.0, "high": 2048.5, "low": 2041.0, "close": 2046.0, "volume": 1200, "timestamp": "2026-03-22T10:01:00Z"},
    {"open": 2046.0, "high": 2050.0, "low": 2045.0, "close": 2049.0, "volume": 1100, "timestamp": "2026-03-22T10:02:00Z"},
    {"open": 2049.0, "high": 2051.0, "low": 2047.0, "close": 2048.5, "volume": 950, "timestamp": "2026-03-22T10:03:00Z"},
    {"open": 2048.5, "high": 2052.0, "low": 2046.0, "close": 2050.5, "volume": 1050, "timestamp": "2026-03-22T10:04:00Z"},
]

class TestResult:
    def __init__(self, component: str, test_name: str):
        self.component = component
        self.test_name = test_name
        self.passed = False
        self.message = ""
        self.data = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "component": self.component,
            "test": self.test_name,
            "status": "✅ PASS" if self.passed else "❌ FAIL",
            "message": self.message,
            "data": self.data
        }

# ============================================================================
# ICT ENGINE TESTS
# ============================================================================
def test_ict_structure_detection() -> TestResult:
    result = TestResult("ICT", "Structure Detection")
    try:
        from astroquant.engine.ict_engine import detect_structure
        import pandas as pd
        df = pd.DataFrame(SAMPLE_CANDLES)
        structure = detect_structure(df)
        result.passed = structure in ["BOS_BULLISH", "BOS_BEARISH", "RANGE"]
        result.message = f"Detected structure: {structure}"
        result.data = {"structure": structure}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_ict_liquidity_sweep() -> TestResult:
    result = TestResult("ICT", "Liquidity Sweep Detection")
    try:
        from astroquant.engine.ict_engine import detect_liquidity_sweep
        import pandas as pd
        df = pd.DataFrame(SAMPLE_CANDLES[-3:])
        sweep = detect_liquidity_sweep(df)
        result.passed = sweep in ["BUY_SIDE_LIQUIDITY_TAKEN", "SELL_SIDE_LIQUIDITY_TAKEN", None]
        result.message = f"Liquidity sweep: {sweep}"
        result.data = {"sweep": sweep}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_ict_fvg_detection() -> TestResult:
    result = TestResult("ICT", "Fair Value Gap (FVG) Detection")
    try:
        from astroquant.engine.ict_engine import detect_fvg
        import pandas as pd
        df = pd.DataFrame(SAMPLE_CANDLES)
        fvg = detect_fvg(df)
        result.passed = fvg is None or "type" in fvg
        result.message = f"FVG detected: {fvg is not None}"
        result.data = {"fvg": fvg}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_ict_order_block() -> TestResult:
    result = TestResult("ICT", "Order Block Detection")
    try:
        from astroquant.engine.ict_engine import detect_order_block
        import pandas as pd
        df = pd.DataFrame(SAMPLE_CANDLES)
        ob = detect_order_block(df)
        result.passed = ob is None or "type" in ob
        result.message = f"Order block detected: {ob is not None}"
        result.data = {"ob": ob}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_ict_turtle_soup() -> TestResult:
    result = TestResult("ICT", "Turtle Soup Detection")
    try:
        from astroquant.engine.ict_engine import detect_turtle_soup
        import pandas as pd
        df = pd.DataFrame(SAMPLE_CANDLES)
        turtle = detect_turtle_soup(df)
        result.passed = turtle in ["SELL_REVERSAL", "BUY_REVERSAL", None]
        result.message = f"Turtle soup: {turtle}"
        result.data = {"turtle_soup": turtle}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_ict_model() -> TestResult:
    result = TestResult("ICT", "ICT Model Signal Generation")
    try:
        from astroquant.engine.models.ict_model import ICTModel
        model = ICTModel()
        test_data = {
            "trend": "UP",
            "liquidity_sweep": True,
            "order_block": "BULLISH",
            "fvg": True,
            "breaker": False
        }
        signal = model.check(test_data, "GC.FUT")
        result.passed = signal is None or "direction" in signal
        result.message = f"Model signal: {signal is not None}"
        result.data = {"signal": signal}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

# ============================================================================
# GANN ENGINE TESTS
# ============================================================================
def test_gann_analysis() -> TestResult:
    result = TestResult("GANN", "Master Gann Analysis")
    try:
        from astroquant.engine.gann.gann_master_engine import GannMasterEngine
        engine = GannMasterEngine()
        analysis = engine.analyze(SAMPLE_CANDLES)
        result.passed = "score" in analysis and analysis["score"] >= 0
        result.message = f"Gann score: {analysis['score']}, confidence: {analysis['confidence']}"
        result.data = {"score": analysis["score"], "confidence": analysis["confidence"]}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_gann_square_of_9() -> TestResult:
    result = TestResult("GANN", "Square of 9 Calculation")
    try:
        from astroquant.engine.gann.gann_master_engine import GannMasterEngine
        engine = GannMasterEngine()
        sq9_data = engine.square9.nearest(2050.5)
        result.passed = sq9_data["level"] is not None
        result.message = f"Nearest SQ9 level: {sq9_data['level']}, bias: {sq9_data['bias']}"
        result.data = sq9_data
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_gann_spiral() -> TestResult:
    result = TestResult("GANN", "Gann Spiral Coordinates")
    try:
        from astroquant.engine.gann.gann_master_engine import GannMasterEngine
        engine = GannMasterEngine()
        spiral = engine.spiral.coordinates(2050.5)
        result.passed = spiral["x"] is not None and spiral["y"] is not None
        result.message = f"Spiral: X={spiral['x']}, Y={spiral['y']}, Theta={spiral['theta']}"
        result.data = spiral
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_gann_degree() -> TestResult:
    result = TestResult("GANN", "Price to Degree Conversion")
    try:
        from astroquant.engine.gann.gann_master_engine import GannMasterEngine
        engine = GannMasterEngine()
        price = 2050.5
        degree = engine.wheel.price_to_degree(price)
        result.passed = 0 <= degree <= 360
        result.message = f"Price {price} → Degree {degree}"
        result.data = {"price": price, "degree": degree}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

# ============================================================================
# ASTROLOGY ENGINE TESTS
# ============================================================================
def test_astrology_planets() -> TestResult:
    result = TestResult("Astrology", "Planet Positions")
    try:
        from astroquant.engine.astro_planets import get_planet_positions
        positions = get_planet_positions()
        result.passed = all(p in positions for p in ["sun", "moon", "mars"])
        result.message = f"Retrieved {len(positions)} planet positions"
        result.data = {k: round(v, 2) for k, v in positions.items()}
    except ImportError as e:
        if "swisseph" in str(e).lower():
            result.message = "swisseph not installed (optional dependency)"
        else:
            result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_astrology_aspects() -> TestResult:
    result = TestResult("Astrology", "Planetary Aspects")
    try:
        from astroquant.engine.astro_planets import get_planet_positions
        from astroquant.engine.astro_aspects import get_aspects
        positions = get_planet_positions()
        aspects = get_aspects(positions)
        result.passed = isinstance(aspects, list)
        result.message = f"Found {len(aspects)} aspects"
        result.data = {"aspect_count": len(aspects), "aspects": [f"{a[0]}-{a[1]}:{a[2]}" for a in aspects[:5]]}
    except ImportError as e:
        if "swisseph" in str(e).lower():
            result.message = "swisseph not installed (optional dependency)"
        else:
            result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

# ============================================================================
# AI MENTOR ENGINE TESTS
# ============================================================================
def test_mentor_engine_initialization() -> TestResult:
    result = TestResult("AI Mentor", "Engine Initialization")
    try:
        from astroquant.backend.ai.mentor_engine import MentorEngine
        engine = MentorEngine()
        result.passed = engine is not None and hasattr(engine, "build_context")
        result.message = "Mentor engine initialized successfully"
        result.data = {"aggressive_mode": engine.aggressive_mode, "disabled_models": list(engine.disabled_models)}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_mentor_htf_bias() -> TestResult:
    result = TestResult("AI Mentor", "HTF Bias Derivation")
    try:
        from astroquant.backend.ai.mentor_engine import MentorEngine
        engine = MentorEngine()
        bias = engine.derive_htf_bias(SAMPLE_CANDLES * 100)
        result.passed = bias in ["BULLISH", "BEARISH", "NEUTRAL"]
        result.message = f"Derived HTF bias: {bias}"
        result.data = {"bias": bias}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_mentor_ltf_structure() -> TestResult:
    result = TestResult("AI Mentor", "LTF Structure Derivation")
    try:
        from astroquant.backend.ai.mentor_engine import MentorEngine
        engine = MentorEngine()
        structure = engine.derive_ltf_structure(SAMPLE_CANDLES * 10)
        result.passed = structure in ["BULLISH", "BEARISH", "RANGE", "EXPANSION", "TREND"]
        result.message = f"Derived LTF structure: {structure}"
        result.data = {"structure": structure}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_mentor_iceberg_detection() -> TestResult:
    result = TestResult("AI Mentor", "Iceberg Pressure Detection")
    try:
        from astroquant.backend.ai.mentor_engine import MentorEngine
        engine = MentorEngine()
        iceberg = engine.derive_iceberg(SAMPLE_CANDLES * 10)
        result.passed = iceberg is None or "detected" in iceberg
        result.message = f"Iceberg detected: {iceberg is not None}"
        result.data = {"iceberg": iceberg}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_mentor_context_building() -> TestResult:
    result = TestResult("AI Mentor", "Context Building")
    try:
        from astroquant.backend.ai.mentor_engine import MentorEngine
        engine = MentorEngine()
        market_data = {
            "symbol": "GC.FUT",
            "canonical_symbol": "XAUUSD",
            "pricing_source": "Databento",
            "htf_bias": "BULLISH",
            "ltf_structure": "TREND",
            "session": "NY",
            "volatility": "NORMAL",
            "news_state": "CLEAR"
        }
        model_data = {
            "name": "ICT",
            "confidence": 85,
            "reason": "Bullish OB + BOS",
            "rr": 3.5,
            "invalid_if": "HTF reversal"
        }
        risk_data = {
            "risk_percent": 2.0,
            "daily_buffer": 500,
            "static_floor": 48000,
            "cooldown": 300
        }
        phase_data = {"phase": "PHASE_1"}
        
        context = engine.build_context(market_data, model_data, risk_data, phase_data)
        result.passed = "market" in context and "model" in context and "risk" in context
        result.message = f"Context built with {len(context)} top-level keys"
        result.data = {"context_keys": list(context.keys())}
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_mentor_model_disable() -> TestResult:
    result = TestResult("AI Mentor", "Model Disable Function")
    try:
        from astroquant.backend.ai.mentor_engine import MentorEngine
        engine = MentorEngine()
        response = engine.disable_model("GANN")
        result.passed = response["status"] == "ok" and "GANN" in response["disabled_models"]
        result.message = f"Disabled models: {response['disabled_models']}"
        result.data = response
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_mentor_ict_sub_engine() -> TestResult:
    result = TestResult("AI Mentor", "ICT Sub-Engine")
    try:
        from astroquant.engine.mentor_ict_engine import MentorICTEngine
        engine = MentorICTEngine()
        market = {"price": 2050.5, "prev_high": 2049.0, "prev_low": 2048.0}
        output = engine.detect(market)
        result.passed = "turtle_soup" in output
        result.message = f"ICT detection: {output['turtle_soup']}"
        result.data = output
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_mentor_gann_sub_engine() -> TestResult:
    result = TestResult("AI Mentor", "GANN Sub-Engine")
    try:
        from astroquant.engine.mentor_gann_engine import MentorGannEngine
        engine = MentorGannEngine()
        market = {"range": 10.0, "low": 2040.0, "bar_count": 150}
        output = engine.calculate(market)
        result.passed = "target_100" in output and "target_200" in output
        result.message = f"GANN targets: T1={output['target_100']}, T2={output['target_200']}"
        result.data = output
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_mentor_astro_sub_engine() -> TestResult:
    result = TestResult("AI Mentor", "Astro Sub-Engine")
    try:
        from astroquant.engine.mentor_astro_engine import MentorAstroEngine
        engine = MentorAstroEngine()
        market = {"astro_window_active": True, "astro_marker": "Sun Trine Pluto", "astro_bias": "Expansion"}
        output = engine.calculate(market)
        result.passed = "planet_event" in output and "harmonic_window" in output
        result.message = f"Astro event: {output['planet_event']}"
        result.data = output
    except ImportError:
        result.message = "Module not available"
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

# ============================================================================
# DASHBOARD ENDPOINTS TESTS
# ============================================================================
def test_broker_bridge_endpoint() -> TestResult:
    result = TestResult("Dashboard", "Broker Bridge Endpoint")
    try:
        import subprocess
        response = subprocess.run(
            ['curl', '-s', 'http://127.0.0.1:8000/status/broker_bridge'],
            capture_output=True,
            text=True,
            timeout=5
        )
        data = json.loads(response.stdout) if response.stdout else {}
        result.passed = "status" in data and "bridge_ready" in data
        result.message = f"Bridge status: {data.get('status', 'UNKNOWN')}"
        result.data = {k: data[k] for k in ["status", "bridge_ready", "same_browser_mode"] if k in data}
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_status_endpoint() -> TestResult:
    result = TestResult("Dashboard", "System Status Endpoint")
    try:
        import subprocess
        response = subprocess.run(
            ['curl', '-s', 'http://127.0.0.1:8000/status'],
            capture_output=True,
            text=True,
            timeout=5
        )
        data = json.loads(response.stdout) if response.stdout else {}
        result.passed = "balance" in data and "phase" in data
        result.message = f"Phase: {data.get('phase')}, Balance: ${data.get('balance')}"
        result.data = {k: data[k] for k in ["balance", "phase", "daily_loss"] if k in data}
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_symbol_registry_endpoint() -> TestResult:
    result = TestResult("Dashboard", "Symbol Registry Endpoint")
    try:
        import subprocess
        response = subprocess.run(
            ['curl', '-s', 'http://127.0.0.1:8000/status/symbol_registry'],
            capture_output=True,
            text=True,
            timeout=5
        )
        data = json.loads(response.stdout) if response.stdout else {}
        result.passed = isinstance(data, (dict, list)) and len(str(data)) > 0
        result.message = f"Registry loaded with {len(data) if isinstance(data, dict) else len(data)} items"
        result.data = {"item_count": len(data) if isinstance(data, dict) else len(data)}
    except Exception as e:
        result.message = f"Error: {str(e)}"
    assert result.passed, result.message
    return result

def test_ai_mentor_endpoint() -> TestResult:
    result = TestResult("Dashboard", "AI Mentor Endpoint")
    try:
        import subprocess
        response = subprocess.run(
            ['curl', '-s', 'http://127.0.0.1:8000/mentor?symbol=GC.FUT'],
            capture_output=True,
            text=True,
            timeout=5
        )
        data = json.loads(response.stdout) if response.stdout else {}
        result.passed = "context" in data or "ict" in data or "gann" in data
        result.message = f"Mentor response containing: {list(data.keys())[:4]}"
        result.data = {"keys": list(data.keys())}
    except Exception as e:
        result.message = f"Error or endpoint not implemented: {str(e)}"
    assert result.passed, result.message
    return result


# ── Lunar Expansion Engine Tests ─────────────────────────────────────────────

def test_lunar_phase_classification() -> TestResult:
    result = TestResult("GANN", "Lunar Phase Classification")
    try:
        from astroquant.engine.gann.lunar_expansion_engine import _classify_phase
        cases = [
            (0.5, "SEED"), (1.9, "SEED"),
            (3.0, "EARLY_EXPANSION"), (5.0, "EARLY_EXPANSION"),
            (7.0, "MOMENTUM"), (9.4, "MOMENTUM"),
            (11.0, "EXHAUSTION"), (13.4, "EXHAUSTION"),
            (13.5, "FULL_MOON_APEX"), (14.9, "FULL_MOON_APEX"),
            (15.5, "DRIFT"), (28.0, "DRIFT"),
        ]
        failures = [f"day={d} expected={e} got={_classify_phase(d)}"
                    for d, e in cases if _classify_phase(d) != e]
        result.passed = len(failures) == 0
        result.message = "All 12 phase cases correct" if result.passed else f"Failures: {failures}"
    except Exception as e:
        result.message = f"Error: {e}"
    assert result.passed, result.message
    return result


def test_lunar_expansion_score() -> TestResult:
    result = TestResult("GANN", "Lunar Expansion Score")
    try:
        from astroquant.engine.gann.lunar_expansion_engine import _expansion_score
        # Score at day 0 ≈ 0, at day 14.76 ≈ 1.0, at day 29 ≈ ~0
        s0   = _expansion_score(0)
        s14  = _expansion_score(14.76)
        s29  = _expansion_score(29.0)
        s9   = _expansion_score(9.0)   # Momentum window: should be ≥0.80
        ok = (s0 <= 0.01 and s14 >= 0.99 and s29 <= 0.07 and s9 >= 0.80)
        result.passed = ok
        result.message = (f"day0={s0:.4f} day9={s9:.4f} day14.76={s14:.4f} day29={s29:.4f}"
                          f" {'OK' if ok else 'FAIL'}")
    except Exception as e:
        result.message = f"Error: {e}"
    assert result.passed, result.message
    return result


def test_lunar_gann_angle() -> TestResult:
    result = TestResult("GANN", "Lunar Gann Wheel Angle")
    try:
        from astroquant.engine.gann.lunar_expansion_engine import _gann_angle, LUNAR_CYCLE
        a0   = _gann_angle(0)
        a_full = _gann_angle(LUNAR_CYCLE / 2)  # Full Moon ≈ 180°
        a_end  = _gann_angle(LUNAR_CYCLE)       # End of cycle ≈ 0°
        ok = (a0 == 0.0 and 178 <= a_full <= 182 and a_end <= 1.0)
        result.passed = ok
        result.message = f"day0={a0}° full={a_full:.2f}° end={a_end:.2f}° {'OK' if ok else 'FAIL'}"
    except Exception as e:
        result.message = f"Error: {e}"
    assert result.passed, result.message
    return result


def test_lunar_live_state() -> TestResult:
    result = TestResult("GANN", "Lunar Expansion Live State")
    try:
        from astroquant.engine.gann.lunar_expansion_engine import compute_lunar_phase, LUNAR_CYCLE
        state = compute_lunar_phase()
        ok = (
            0.0 <= state.cycle_day <= LUNAR_CYCLE
            and state.phase in ("SEED", "EARLY_EXPANSION", "MOMENTUM",
                                "EXHAUSTION", "FULL_MOON_APEX", "DRIFT", "TRANSITION")
            and 0.0 <= state.expansion_score <= 1.0
            and 0.0 <= state.gann_angle < 360.0
            and isinstance(state.waxing, bool)
            and len(state.lesson_note) > 10
        )
        result.passed = ok
        result.message = (f"day={state.cycle_day:.2f} phase={state.phase} "
                          f"score={state.expansion_score:.3f} "
                          f"angle={state.gann_angle}° waxing={state.waxing}")
        result.data = {"phase": state.phase, "cycle_day": state.cycle_day}
    except Exception as e:
        result.message = f"Error: {e}"
    assert result.passed, result.message
    return result


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================
def run_all_tests() -> List[TestResult]:
    """Run all test suites"""
    tests = [
        # ICT Tests
        test_ict_structure_detection,
        test_ict_liquidity_sweep,
        test_ict_fvg_detection,
        test_ict_order_block,
        test_ict_turtle_soup,
        test_ict_model,
        
        # GANN Tests
        test_gann_analysis,
        test_gann_square_of_9,
        test_gann_spiral,
        test_gann_degree,
        # Lunar Expansion Engine Tests (Gann Lesson 1)
        test_lunar_phase_classification,
        test_lunar_expansion_score,
        test_lunar_gann_angle,
        test_lunar_live_state,
        
        # Astrology Tests
        test_astrology_planets,
        test_astrology_aspects,
        
        # AI Mentor Tests
        test_mentor_engine_initialization,
        test_mentor_htf_bias,
        test_mentor_ltf_structure,
        test_mentor_iceberg_detection,
        test_mentor_context_building,
        test_mentor_model_disable,
        test_mentor_ict_sub_engine,
        test_mentor_gann_sub_engine,
        test_mentor_astro_sub_engine,
        
        # Dashboard Tests
        test_broker_bridge_endpoint,
        test_status_endpoint,
        test_symbol_registry_endpoint,
        test_ai_mentor_endpoint,
    ]
    
    results = []
    for test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            result = TestResult(test_func.__name__.split("_")[1].upper(), test_func.__name__)
            result.message = f"Test execution failed: {str(e)}"
            results.append(result)
    
    return results

def print_report(results: List[TestResult]) -> int:
    """Print comprehensive test report"""
    print("\n" + "="*100)
    print("ASTROQUANT COMPREHENSIVE TEST REPORT")
    print("="*100)
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Total Tests: {len(results)}")
    print()
    
    # Group by component
    components = {}
    for result in results:
        if result.component not in components:
            components[result.component] = []
        components[result.component].append(result)
    
    # Print by component
    for component in sorted(components.keys()):
        component_results = components[component]
        passed = sum(1 for r in component_results if r.passed)
        total = len(component_results)
        
        print(f"\n{'─'*100}")
        print(f"📊 {component.upper()} ({passed}/{total} PASSED)")
        print(f"{'─'*100}")
        
        for result in component_results:
            status_icon = "✅" if result.passed else "❌"
            print(f"{status_icon} {result.test_name:40} | {result.message}")
            if result.data:
                try:
                    data_str = json.dumps(result.data, indent=0)[:60]
                    print(f"   └─ {data_str}")
                except:
                    pass
    
    # Summary
    all_passed = sum(1 for r in results if r.passed)
    print(f"\n{'='*100}")
    print(f"SUMMARY: {all_passed}/{len(results)} tests passed ({all_passed*100//len(results) if len(results) > 0 else 0}%)")
    print(f"{'='*100}\n")
    
    # Return exit code
    return 0 if all_passed == len(results) else 1

if __name__ == "__main__":
    results = run_all_tests()
    exit_code = print_report(results)
    sys.exit(exit_code)
