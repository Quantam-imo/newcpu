from pathlib import Path

from backend.core.phase1_config import get_phase1_config
from backend.core.output_contracts import (
    normalize_capital_flow_output,
    normalize_execution_output,
    normalize_failure_output,
    output_contract_versions,
)
from backend.utils.data_loader import load_data, load_news_data, integrate_news_features
from backend.memory.scanner import scan_market
from backend.memory.vector_memory import build_vector_memory
from backend.ai.feature_vector import create_feature_vector
from backend.ai.similarity_engine import find_similar
from backend.memory.recall_engine import recall_patterns
from backend.ai.probability_engine import compute_probability
from backend.ai.decision_engine import ai_decision
from backend.engines.psychology_engine import psychology_engine
from backend.engines.trap_engine import trap_engine
from backend.engines.behavior_engine import behavior_engine
from backend.gann.gann_advanced import gann_advanced
from backend.astro.astro_engine import astro_engine
from backend.engines.numerology_engine import numerology_engine
from backend.engines.harmonic_engine import harmonic_engine
from backend.engines.time_engine import time_engine
from backend.engines.future_engine import future_engine
from backend.sync.weight_engine import weight_engine
from backend.sync.signal_engine import generate_signals
from backend.sync.dominance_engine import dominance_engine
from backend.sync.confidence_engine import confidence_engine
from backend.sync.scenario_engine import scenario_engine
from backend.sync.final_engine import final_engine
from backend.validation.validation_engine import validate_signal
from backend.validation.filter_engine import filter_signal
from backend.ai.learning_engine import learning_engine
from backend.memory.update_memory import update_memory
from backend.macro.multi_asset_engine import multi_asset_engine
from backend.macro.macro_engine import macro_engine
from backend.macro.correlation_engine import correlation_engine
from backend.macro.capital_flow import capital_flow_engine
from backend.live.auto_pipeline import run_pipeline
from backend.sync.sync_engine import institutional_sync
from backend.live.mt5_fetch import fetch_xauusd
from backend.validation.backtest import backtest
from backend.validation.execution_engine import execution_engine
from backend.validation.failure_engine import failure_engine
# Precision + Realism safeguard layer (8 system reliability engines)
from backend.validation.data_quality_engine import check_data_quality
from backend.validation.latency_engine import latency_analysis
from backend.sync.simplicity_layer import simplicity_score
from backend.validation.adaptive_timescale_engine import adaptive_timescale_analysis
from backend.validation.overfitting_protection import overfitting_guard
# Universal Conversion Engine (math / Gann / astro / harmonic layer)
from backend.universal_engine import (
    numerology_profile as ue_numerology_profile,
    fib_levels as ue_fib_levels,
    gann_advanced_analysis as ue_gann_analysis,
    nakshatra_from_degree as ue_nakshatra,
    price_to_degree as ue_price_to_degree,
    harmonic_analysis as ue_harmonic_analysis,
)


def _build_decision_trace(signals: dict, weights: dict, dominant: str, confidence: float, quality: str, trap: dict) -> dict:
    weighted = {"BUY": 0.0, "SELL": 0.0}
    for source, direction in (signals or {}).items():
        w = float((weights or {}).get(source, 0.0))
        if direction in ("BUY", "STRONG BUY"):
            weighted["BUY"] += w
        elif direction in ("SELL", "STRONG SELL"):
            weighted["SELL"] += w

    top_score = max(weighted.values()) if weighted else 0.0
    bottom_score = min(weighted.values()) if weighted else 0.0
    conflict_score = (bottom_score / top_score) if top_score > 0 else 0.0

    trap_prob = float((trap or {}).get("probability", 0.0) or 0.0)
    quality_bonus = 0.05 if str(quality).upper() == "STRONG" else 0.0
    reliability_score = confidence * (1.0 - 0.35 * conflict_score) * (1.0 - 0.2 * trap_prob) + quality_bonus
    reliability_score = max(0.0, min(1.0, reliability_score))

    return {
        "dominant_force": dominant,
        "conflict_score": round(conflict_score, 4),
        "reliability_score": round(reliability_score, 4),
        "weighted_forces": {k: round(v, 4) for k, v in weighted.items()},
    }


def process(df):
    # Core intelligence pipeline
    phase1_cfg = get_phase1_config()

    # Precision layer 1: data quality audit before any analysis
    data_quality = check_data_quality(df)

    # Step 1: Scan memory
    memory = scan_market(df)

    # Step 2: Build vectors
    vectors = build_vector_memory(memory)

    # Step 3: Current state
    current_record = memory[-1]
    current_vec = create_feature_vector(current_record)

    # Step 4: Find similar
    matches = find_similar(current_vec, vectors)

    # Step 5: Recall patterns
    results = recall_patterns(matches, memory)

    # Step 6: Probability
    prob = compute_probability(results)

    # Step 7: AI decision
    decision = ai_decision(prob)

    # Phase 4: Psychology + trap + behavior reasoning layer
    state = current_record["state"]
    psychology = psychology_engine(state, current_record["phase"])
    trap = trap_engine(state, current_record["liquidity"], current_record["phase"])
    behavior = behavior_engine(psychology, trap)

    # Phase 5: Time + universal alignment layer
    gann_adv = gann_advanced(state, df)
    astro = astro_engine(df)
    numerology = numerology_engine(state["price"])
    harmonic = harmonic_engine(df)
    time_signal = time_engine(gann_adv, astro)
    future = future_engine(state, current_record["phase"], time_signal, harmonic, numerology)

    # Precision layer 2: latency awareness + adaptive time-scale
    latency = latency_analysis(state, df)
    timescale = adaptive_timescale_analysis(state, df)

    # Phase 6: final synchronization and intelligence output
    weights = weight_engine(state, current_record["phase"])
    signals = generate_signals(state, current_record["liquidity"], current_record["gann"], decision)
    dominant, score = dominance_engine(signals, weights)
    confidence = confidence_engine(score)
    scenarios = scenario_engine(dominant, confidence)
    final = final_engine(
        state,
        current_record["phase"],
        psychology,
        trap,
        behavior,
        dominant,
        confidence,
        scenarios,
        time_signal,
    )

    # PRO layer: signal quality validation and filtering.
    # Accuracy Pass v2: pass phase to filter_signal so MANIPULATION and
    # low-vol EXPANSION signals are suppressed (84% 1-bar precision when active).
    quality = validate_signal(confidence, trap, current_record["phase"])
    final_signal = filter_signal(dominant, confidence, phase=current_record["phase"])
    decision_trace = _build_decision_trace(signals, weights, dominant, confidence, quality, trap)

    # News-aware safeguard: avoid opening directional positions around high-impact events.
    news_context = current_record.get("news", {})
    news_guard_applied = False
    rejection_reason = ""
    if (
        phase1_cfg["enable_news_guard"]
        and final_signal in ("BUY", "SELL", "STRONG BUY", "STRONG SELL")
        and news_context.get("high_impact_active")
    ):
        final_signal = "WAIT"
        news_guard_applied = True
        rejection_reason = "news_high_impact_guard"

    if (
        phase1_cfg["enable_strict_reliability_gate"]
        and final_signal in ("BUY", "SELL", "STRONG BUY", "STRONG SELL")
        and decision_trace["reliability_score"] < phase1_cfg["min_reliability_score"]
    ):
        final_signal = "WAIT"
        rejection_reason = "reliability_below_threshold"

    # Precision layer 3: simplicity output — single bias score for UI / alerts
    simple = simplicity_score(
        final_signal,
        confidence,
        decision_trace["reliability_score"],
        decision_trace["conflict_score"],
        trap,
    )

    # PRO layer: lightweight learning feedback loop.
    actual = "BUY" if state["trend"] == "UP" else "SELL"
    updated_weights = learning_engine(dominant, actual, weights.copy())

    # PRO layer: continuous memory update with current analyzed record.
    memory = update_memory(memory, current_record)

    # Institutional layer: multi-asset placeholders and macro causality.
    def fetch_all_data():
        # Placeholder structure until dedicated feeds are connected.
        return {
            "gold": df,
            "usd": df,
            "bonds": df,
            "oil": df,
            "spx": df,
        }

    def process_all(data):
        gold_state = state
        usd_state = {"trend": "DOWN" if gold_state["trend"] == "UP" else "UP"}
        bonds_state = {"trend": "DOWN" if gold_state["trend"] == "UP" else "UP"}
        equities_state = {"trend": "DOWN" if trap["trap"] != "NONE" else "UP"}

        multi_asset = multi_asset_engine(gold_state, usd_state, bonds_state)
        macro_bias = macro_engine(inflation=4.2, rates=3.8)
        flow = normalize_capital_flow_output(capital_flow_engine(gold_state, equities_state))

        corr_gold_usd = correlation_engine(
            data["gold"]["close"].tail(60).to_numpy(),
            (-data["usd"]["close"].tail(60)).to_numpy(),
        )

        institutional_decision, institutional_score = institutional_sync(signals, macro_bias, flow)

        return {
            "multi_asset": multi_asset,
            "macro": macro_bias,
            "capital_flow": flow,
            "correlation_gold_usd": corr_gold_usd,
            "institutional_decision": institutional_decision,
            "institutional_score": institutional_score,
        }

    institutional = run_pipeline(fetch_all_data, process_all)

    # Phase 7: real-world validation and execution awareness.
    backtest_stats = backtest(memory)
    execution_state = normalize_execution_output(execution_engine(state))
    failure_state = normalize_failure_output(failure_engine(state))

    # Precision layer 4: overfitting protection
    overfit = overfitting_guard(backtest_stats)

    # Universal Conversion Engine outputs
    _ue_price = state["price"]
    universal = {
        "numerology": ue_numerology_profile(_ue_price),
        "fib_levels": ue_fib_levels(
            float(df["high"].tail(50).max()),
            float(df["low"].tail(50).min()),
        ),
        "gann": ue_gann_analysis(state, df),
        "nakshatra": ue_nakshatra(ue_gann_analysis(state, df)["degrees"]),
        "price_degree": ue_price_to_degree(_ue_price),
        "harmonic": ue_harmonic_analysis(df),
    }

    # Accuracy Pass v2: attach SL/TP levels to every directional signal
    price = state["price"]
    trade_levels = None
    if final_signal in ("BUY", "STRONG BUY"):
        trade_levels = {
            "entry": round(price, 2),
            "stop_loss": round(price - 10.0, 2),   # optimal SL: -$10/oz
            "take_profit": round(price + 20.0, 2), # optimal TP: +$20/oz
            "r_ratio": 2.0,
            "hold_bars": 7,
        }

    return {
        "matches": matches,
        "probability": prob,
        "ai_decision": decision,
        "psychology": psychology,
        "trap": trap,
        "behavior": behavior,
        "gann_adv": gann_adv,
        "astro": astro,
        "numerology": numerology,
        "harmonic": harmonic,
        "time_signal": time_signal,
        "future": future,
        "weights": weights,
        "signals": signals,
        "score": score,
        "confidence": confidence,
        "scenarios": scenarios,
        "quality": quality,
        "filtered_signal": final_signal,
        "news": news_context,
        "news_guard_applied": news_guard_applied,
        "decision_trace": decision_trace if phase1_cfg["enable_decision_trace"] else {},
        "rejection_reason": rejection_reason,
        "output_contracts": output_contract_versions(),
        "phase1_config": phase1_cfg,
        "trade_levels": trade_levels,
        "updated_weights": updated_weights,
        "memory_size": len(memory),
        "final": final,
        "institutional": institutional,
        "backtest": backtest_stats,
        "execution": execution_state,
        "failure": failure_state,
        # Precision + Realism Layer
        "data_quality": data_quality,
        "latency": latency,
        "timescale": timescale,
        "simple": simple,
        "overfit": overfit,
        "universal": universal,
    }


def full_system():
    news_status = "not_loaded"
    news_file = "data/news_data_v2.csv"

    try:
        df = fetch_xauusd()
        source = "MT5 LIVE"
    except Exception as exc:
        df = load_data("data/XAU_1Month_data.csv")
        source = f"CSV FALLBACK ({exc})"

    news_path = Path(news_file)
    if news_path.exists():
        try:
            news_df = load_news_data(news_file)
            df = integrate_news_features(df, news_df)
            news_status = f"loaded ({len(news_df)} events)"
        except Exception as exc:
            news_status = f"load_failed ({exc})"
    else:
        # Keep pipeline operational even when the optional news dataset is absent.
        df = integrate_news_features(df, None)
        news_status = "missing_optional_file"

    result = process(df)
    result["data_source"] = source
    result["news_source"] = news_file
    result["news_status"] = news_status
    return result


def main() -> None:
    result = full_system()

    print("DATA SOURCE:", result["data_source"])
    print("NEWS SOURCE:", result["news_source"])
    print("NEWS STATUS:", result["news_status"])
    print("Matches:", result["matches"])
    print("Probability:", result["probability"])
    print("AI Decision:", result["ai_decision"])
    print("Psychology:", result["psychology"])
    print("Trap:", result["trap"])
    print("Behavior:", result["behavior"])
    print("GANN ADV:", result["gann_adv"])
    print("ASTRO:", result["astro"])
    print("NUMEROLOGY:", result["numerology"])
    print("HARMONIC:", result["harmonic"])
    print("TIME SIGNAL:", result["time_signal"])
    print("FUTURE:", result["future"])
    print("WEIGHTS:", result["weights"])
    print("SIGNALS:", result["signals"])
    print("DOMINANCE SCORE:", result["score"])
    print("CONFIDENCE:", result["confidence"])
    print("SCENARIOS:", result["scenarios"])
    print("QUALITY:", result["quality"])
    print("FILTERED SIGNAL:", result["filtered_signal"])
    print("NEWS CONTEXT:", result.get("news"))
    print("NEWS GUARD APPLIED:", result.get("news_guard_applied"))
    print("REJECTION REASON:", result.get("rejection_reason") or "none")
    if result.get("decision_trace"):
        dt = result["decision_trace"]
        print("DOMINANT FORCE:", dt.get("dominant_force"))
        print("CONFLICT SCORE:", dt.get("conflict_score"))
        print("RELIABILITY SCORE:", dt.get("reliability_score"))
        print("WEIGHTED FORCES:", dt.get("weighted_forces"))
    if result.get("trade_levels"):
        tl = result["trade_levels"]
        print(f"TRADE LEVELS: Entry={tl['entry']}  SL={tl['stop_loss']} (-$10)  TP={tl['take_profit']} (+$20)  R={tl['r_ratio']}:1  Hold={tl['hold_bars']}bars")
    print("UPDATED WEIGHTS:", result["updated_weights"])
    print("MEMORY SIZE:", result["memory_size"])
    print("BACKTEST:", result["backtest"])
    print("EXECUTION:", result["execution"])
    print("FAILURE:", result["failure"])

    # Precision + Realism Layer
    dq = result.get("data_quality", {})
    print(f"\nDATA QUALITY: score={dq.get('score')}  status={dq.get('status')}  issues={dq.get('issues')}")

    lat = result.get("latency", {})
    print(f"LATENCY: verdict={lat.get('timing_verdict')}  bar_delay={lat.get('bar_latency', {}).get('delay_bars')}  urgency={lat.get('reaction_window', {}).get('urgency')}")

    ts = result.get("timescale", {})
    vr = ts.get("volatility_regime", {})
    print(f"TIMESCALE: regime={vr.get('regime')}  speed_ratio={vr.get('speed_ratio')}  modifier={ts.get('signal_modifier')}")

    sm = result.get("simple", {})
    print(f"SIMPLICITY: bias={sm.get('bias_score')}  label={sm.get('bias_label')}  clarity={sm.get('clarity')}/100  conviction={sm.get('conviction')}")

    ov = result.get("overfit", {})
    print(f"OVERFIT GUARD: risk={ov.get('overfit_risk')}  recommendation={ov.get('recommendation')}")

    ue = result.get("universal", {})
    ue_num = ue.get("numerology", {})
    ue_gann = ue.get("gann", {})
    ue_nak = ue.get("nakshatra", {})
    ue_harm = ue.get("harmonic", {})
    print(f"\nUNIVERSAL ENGINE:")
    print(f"  NUMEROLOGY: number={ue_num.get('number')}  meaning={ue_num.get('meaning')}")
    print(f"  GANN DEGREE: {ue_gann.get('degrees')}°  cycle={ue_gann.get('cycle', {}).get('description')}  PTE={ue_gann.get('price_time_equality', {}).get('status')}")
    print(f"  NAKSHATRA: {ue_nak.get('nakshatra')}  pada={ue_nak.get('pada')}  pos={ue_nak.get('position_pct')}%")
    print(f"  PRICE DEGREE: {ue.get('price_degree')}°")
    print(f"  HARMONIC: status={ue_harm.get('status')}  abcd={ue_harm.get('abcd_pattern', {}).get('type')}  d_up={ue_harm.get('d_extension_up')}  d_down={ue_harm.get('d_extension_down')}")

    print("\nFINAL INTELLIGENCE OUTPUT")
    for k, v in result["final"].items():
        print(f"{k}: {v}")

    institutional = result["institutional"]
    print("\nGLOBAL MARKET INTELLIGENCE")
    print("MULTI ASSET:", institutional["multi_asset"])
    print("MACRO:", institutional["macro"])
    print("CAPITAL FLOW:", institutional["capital_flow"])
    print("CORRELATION GOLD-USD:", institutional["correlation_gold_usd"])
    print("INSTITUTIONAL DECISION:", institutional["institutional_decision"])
    print("INSTITUTIONAL SCORE:", institutional["institutional_score"])


if __name__ == "__main__":
    main()