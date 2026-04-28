from __future__ import annotations

from pathlib import Path
from typing import Any

# Wheel-model components (imported lazily to keep backward-compat)
_WHEEL_MODEL_PATH = Path(__file__).parent.parent.parent / "data" / "ai_models" / "wheel_transition.json"


def _load_transition_model():
    """Lazy-load the WheelTransitionModel."""
    try:
        from backend.engines.transition_model import WheelTransitionModel
        return WheelTransitionModel.load(_WHEEL_MODEL_PATH)
    except Exception:
        return None


_CACHED_WHEEL_MODEL = None
_WHEEL_ONLINE_UPDATE_COUNTER = 0


def _wheel_model():
    global _CACHED_WHEEL_MODEL
    if _CACHED_WHEEL_MODEL is None:
        _CACHED_WHEEL_MODEL = _load_transition_model()
    return _CACHED_WHEEL_MODEL


def adapt_wheel_transition_online(
    previous_phase: int,
    current_phase: int,
    context_key: str | None = None,
    learning_rate: float = 1.0,
    decay: float = 0.0005,
    persist_every: int = 25,
) -> dict[str, Any]:
    """
    Online adaptation hook for wheel rotation model.
    Applies one observed transition and periodically persists model to disk.
    """
    global _WHEEL_ONLINE_UPDATE_COUNTER

    wm = _wheel_model()
    if wm is None:
        return {"updated": False, "reason": "wheel_model_not_loaded"}

    result = wm.update_online(
        previous_phase=previous_phase,
        current_phase=current_phase,
        context_key=context_key,
        learning_rate=learning_rate,
        decay=decay,
    )

    if not result.get("updated"):
        return result

    _WHEEL_ONLINE_UPDATE_COUNTER += 1
    persisted = False
    if persist_every > 0 and (_WHEEL_ONLINE_UPDATE_COUNTER % int(persist_every) == 0):
        try:
            wm.save(_WHEEL_MODEL_PATH)
            persisted = True
        except Exception as exc:
            result["persist_error"] = str(exc)

    result["online_update_counter"] = _WHEEL_ONLINE_UPDATE_COUNTER
    result["persisted"] = persisted
    return result


# ---------------------------------------------------------------------------
# Legacy single-dict probability threshold (kept for backward-compat callers
# that still pass {"BUY": p, "SELL": 1-p}).
# ---------------------------------------------------------------------------

def ai_decision(prob: dict[str, float]) -> str:
    """Return BUY / SELL / WAIT from a raw probability dict."""
    if (prob.get("BUY") or 0.0) > 0.6:
        return "BUY"
    if (prob.get("SELL") or 0.0) > 0.6:
        return "SELL"
    return "WAIT"


# ---------------------------------------------------------------------------
# Multi-factor confluence decision engine.
# Produces a structured dict with direction, confidence, sl/tp guidance and
# a per-factor scoring breakdown so callers can explain every decision.
# ---------------------------------------------------------------------------

_HARMONIC_REVERSAL_DEGREES = {0.0, 45.0, 90.0, 120.0, 144.0, 180.0, 216.0, 240.0, 270.0, 315.0, 360.0}


def _near_harmonic(deg: float, tolerance: float = 12.0) -> bool:
    return any(abs(((deg - h + 180) % 360) - 180) <= tolerance for h in _HARMONIC_REVERSAL_DEGREES)


def _absorption_strength_bucket(absorption_score: float, flow_imbalance: float) -> str:
    absorption_mag = max(abs(absorption_score), abs(flow_imbalance))
    if absorption_mag >= 0.75:
        return "ABSORB_HIGH"
    if absorption_mag >= 0.40:
        return "ABSORB_MED"
    return "ABSORB_LOW"


def build_wheel_context_inputs(
    memory_last: dict[str, Any] | None = None,
    regime_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build the runtime wheel conditioning tuple used by both inference and
    online adaptation.

    Returns
    -------
    {
      "context_key": str | None,
      "regime": str | None,
      "volatility_bucket": str,
      "liquidity_state": str,
      "absorption_side": str,
      "absorption_strength": str,
      "absorption_score": float,
      "flow_imbalance": float,
    }
    """
    mem = memory_last or {}
    order_flow = mem.get("order_flow") or {}
    liq_type = str(mem.get("liquidity", {}).get("type") or "NONE").upper()

    regime_key = (regime_result or {}).get("regime")
    atr_z = float((regime_result or {}).get("atr_z", 0.0))
    vol_bucket = "HIGH_VOL" if atr_z > 1.5 else ("LOW_VOL" if atr_z < 0.5 else "MED_VOL")
    liq_state = "SWEEP" if liq_type in ("BUY_SIDE_SWEEP", "SELL_SIDE_SWEEP") else "NO_SWEEP"

    of_side = str(order_flow.get("aggressive_side") or "NEUTRAL").upper()
    of_imbalance = float(order_flow.get("flow_imbalance") or 0.0)
    iceberg = bool(order_flow.get("iceberg_detected", False))
    iceberg_side = str(order_flow.get("iceberg_side") or "NONE").upper()
    absorption_score = float(order_flow.get("iceberg_absorption_score") or 0.0)

    absorption_side = "NEUTRAL"
    if iceberg and iceberg_side in {"BUY", "SELL"} and absorption_score >= 0.55:
        absorption_side = iceberg_side
    elif of_side in {"BUY", "SELL"} and abs(of_imbalance) >= 0.12:
        absorption_side = of_side

    absorption_strength = _absorption_strength_bucket(absorption_score, of_imbalance)

    context_key = None
    try:
        from backend.engines.transition_model import WheelTransitionModel

        context_key = WheelTransitionModel.build_context_key(
            regime=regime_key,
            volatility_bucket=vol_bucket,
            liquidity_state=liq_state,
            absorption_side=absorption_side,
            absorption_strength=absorption_strength,
        )
    except Exception:
        context_key = None

    return {
        "context_key": context_key,
        "regime": regime_key,
        "volatility_bucket": vol_bucket,
        "liquidity_state": liq_state,
        "absorption_side": absorption_side,
        "absorption_strength": absorption_strength,
        "absorption_score": absorption_score,
        "flow_imbalance": of_imbalance,
    }


def confluence_decision(
    model_meta: dict[str, Any],
    memory_last: dict[str, Any] | None = None,
    regime_result: dict[str, Any] | None = None,
    phase_labeled: int | None = None,
) -> dict[str, Any]:
    """
    Multi-factor confluence gate — extended with Wheel Rotation layer.

    Parameters
    ----------
    model_meta    : dict returned by serving.decide_with_model()
                    Must contain at minimum: p_buy, p_sell, used_model.
    memory_last   : The last memory record from scan_market() — used to pull
                    wheel, Elliott, session, trap and AMD state.
    regime_result : dict from regime_detector.detect_regime() — optional.
                    If provided, scales all factor scores by decision_weight.
    phase_labeled : Current phase code (0=Accum, 1=Manip, 2=Expansion, 3=Distrib)
                    from phase_labeler.get_current_phase().
                    If None, the function falls back to the string phase in memory.

    Returns
    -------
    {
        direction          : "BUY" | "SELL" | "WAIT",
        confidence         : 0.0-1.0,
        confluence_score   : int   (0-10, higher = stronger),
        skip_reason        : str | None,
        sl_zone            : float | None,  # approximate level
        tp_zone            : float | None,
        wheel_transition   : dict | None,   # next-phase prediction from transition model
        regime             : str | None,
        factor_breakdown   : dict  (per-factor detail),
    }
    """
    mem = memory_last or {}
    p_buy: float = float(model_meta.get("p_buy") or 0.5)
    p_sell: float = float(model_meta.get("p_sell") or (1.0 - p_buy))
    model_used: bool = bool(model_meta.get("used_model", False))

    # Pull context sub-dicts from last memory record
    obs = mem.get("gann_astro_math") or {}
    ell = mem.get("elliott_wave") or {}
    participation = mem.get("participation") or {}
    order_flow = mem.get("order_flow") or {}
    trigger = mem.get("trigger") or {}
    trap = mem.get("trap") or {}
    location = mem.get("location") or {}
    structure = mem.get("structure") or {}
    phase = str(mem.get("phase") or "").upper()
    state = mem.get("state") or {}
    reliability = mem.get("reliability") or {}
    amd = mem.get("amd_ifvg") or {}

    # ==================================================================
    # HIERARCHICAL CONFLUENCE SCORING
    # ==================================================================
    # The scoring is split into three tiers:
    #
    #   PRIMARY   — "must agree" conditions.  These are the slowest,
    #               most reliable signals: phase state + a confirmed
    #               liquidity event.  A directional call is BLOCKED
    #               unless at least one PRIMARY condition fires in the
    #               intended direction.
    #
    #   SECONDARY — confidence amplifiers.  Model probability and
    #               regime provide the quantitative weight.  They
    #               amplify or reduce the final score but cannot
    #               alone override a failed PRIMARY gate.
    #
    #   TERTIARY  — context filters.  Astro, Gann harmonics,
    #               Elliott wave, session, numerology.  These add
    #               fractional confidence; they are NOT allowed to
    #               initiate a signal on their own.
    #
    # Final decision:
    #   direction is issued only when
    #     (a) PRIMARY gate passes in that direction, AND
    #     (b) total_score (primary + secondary + tertiary) ≥ regime_threshold
    # ==================================================================

    factors: dict[str, Any] = {}

    # ---- PRIMARY scores (weight 3 each) ----
    primary_buy   = 0.0
    primary_sell  = 0.0

    # PRIMARY 1 — Phase state confirms direction
    _phase_map = {"ACCUMULATION": 0, "MANIPULATION": 1, "EXPANSION": 2, "DISTRIBUTION": 3}
    _phase_code_from_mem = _phase_map.get(phase)
    _effective_phase_code = phase_labeled if phase_labeled is not None else _phase_code_from_mem

    if _effective_phase_code == 0:          # ACCUMULATION → bias long
        primary_buy += 3.0
        factors["phase_primary"] = "BUY+3 (ACCUMULATION: demand building)"
    elif _effective_phase_code == 1:        # MANIPULATION → wait for trap confirmation
        trap_type = str(trap.get("trap") or "NONE").upper()
        if "BUYER" in trap_type:
            primary_sell += 3.0
            factors["phase_primary"] = "SELL+3 (MANIPULATION: buyer trap confirmed)"
        elif "SELLER" in trap_type:
            primary_buy += 3.0
            factors["phase_primary"] = "BUY+3 (MANIPULATION: seller trap confirmed)"
        else:
            factors["phase_primary"] = "BLOCKED (MANIPULATION phase: no trap confirmed yet)"
    elif _effective_phase_code == 2:        # EXPANSION → ride the trend
        if structure.get("hh_hl"):
            primary_buy += 3.0
            factors["phase_primary"] = "BUY+3 (EXPANSION: higher-high/higher-low structure)"
        else:
            primary_sell += 3.0
            factors["phase_primary"] = "SELL+3 (EXPANSION: lower-high/lower-low structure)"
    elif _effective_phase_code == 3:        # DISTRIBUTION → fade the trend
        if structure.get("hh_hl"):
            primary_sell += 3.0
            factors["phase_primary"] = "SELL+3 (DISTRIBUTION: smart money exiting uptrend)"
        else:
            primary_buy += 3.0
            factors["phase_primary"] = "BUY+3 (DISTRIBUTION: smart money exiting downtrend)"
    else:
        factors["phase_primary"] = "NONE (phase unknown)"

    # PRIMARY 2 — Liquidity event (sweep) required as trigger
    liq_type = str(mem.get("liquidity", {}).get("type") or "NONE").upper()
    if liq_type == "SELL_SIDE_SWEEP":
        primary_buy += 3.0
        factors["liquidity_primary"] = "BUY+3 (sell-side liquidity swept → reversal trigger)"
    elif liq_type == "BUY_SIDE_SWEEP":
        primary_sell += 3.0
        factors["liquidity_primary"] = "SELL+3 (buy-side liquidity swept → reversal trigger)"
    else:
        factors["liquidity_primary"] = f"NONE (liquidity={liq_type}: no sweep trigger)"

    # ---- SECONDARY scores (weight 2 each) ----
    secondary_buy  = 0.0
    secondary_sell = 0.0

    # SECONDARY 1 — AI model probability
    if model_used:
        if p_buy >= 0.65:
            secondary_buy += 2.0
            factors["model"] = f"BUY+2 (p_buy={p_buy:.3f})"
        elif p_buy >= 0.58:
            secondary_buy += 1.0
            factors["model"] = f"BUY+1 (p_buy={p_buy:.3f})"
        elif p_sell >= 0.65:
            secondary_sell += 2.0
            factors["model"] = f"SELL+2 (p_sell={p_sell:.3f})"
        elif p_sell >= 0.58:
            secondary_sell += 1.0
            factors["model"] = f"SELL+1 (p_sell={p_sell:.3f})"
        else:
            factors["model"] = f"NEUTRAL (p_buy={p_buy:.3f})"
    else:
        factors["model"] = f"NOT_USED ({model_meta.get('reason', 'n/a')})"

    # SECONDARY 2 — ICT trigger (sweep + MSS + displacement)
    trigger_dir = str(trigger.get("trigger_direction") or "WAIT").upper()
    trigger_confirmed = bool(trigger.get("trigger_confirmed", False))
    if trigger_confirmed and trigger_dir == "BUY":
        secondary_buy += 2.0
        factors["ict_trigger"] = "BUY+2 (sweep+MSS+displacement confirmed)"
    elif trigger_confirmed and trigger_dir == "SELL":
        secondary_sell += 2.0
        factors["ict_trigger"] = "SELL+2 (sweep+MSS+displacement confirmed)"
    else:
        factors["ict_trigger"] = f"NONE (trigger_dir={trigger_dir})"

    # SECONDARY 3 — Wheel transition model
    wheel_transition: dict | None = None
    _phase_code_for_wheel = phase_labeled if phase_labeled is not None else _phase_code_from_mem

    if _phase_code_for_wheel is not None:
        wm = _wheel_model()
        if wm is not None:
            try:
                wheel_ctx = build_wheel_context_inputs(mem, regime_result)
                wheel_transition = wm.predict(
                    _phase_code_for_wheel,
                    context_key=wheel_ctx.get("context_key"),
                    regime=wheel_ctx.get("regime"),
                    volatility_bucket=wheel_ctx.get("volatility_bucket"),
                    liquidity_state=wheel_ctx.get("liquidity_state"),
                    absorption_side=wheel_ctx.get("absorption_side"),
                    absorption_strength=wheel_ctx.get("absorption_strength"),
                )
                next_phase = wheel_transition.get("next_phase", -1)
                next_conf  = wheel_transition.get("confidence", 0.0)
                ctx_used   = wheel_transition.get("context_used", "unconditional")
                factors["wheel_context"] = (
                    f"ctx={ctx_used} runtime={wheel_ctx.get('context_key') or 'none'} "
                    f"abs={wheel_ctx.get('absorption_side')}|{wheel_ctx.get('absorption_strength')}"
                )

                if _phase_code_for_wheel == 0 and next_phase == 2 and next_conf >= 0.55:
                    secondary_buy += 2.0
                    factors["wheel_transition"] = f"BUY+2 (ACCUM→EXPANSION P={next_conf:.2f} ctx={ctx_used})"
                elif _phase_code_for_wheel == 1 and next_phase == 2 and next_conf >= 0.60:
                    if primary_sell > primary_buy:
                        secondary_sell += 2.0
                        factors["wheel_transition"] = f"SELL+2 (MANIP→EXPANSION short P={next_conf:.2f} ctx={ctx_used})"
                    else:
                        secondary_buy += 2.0
                        factors["wheel_transition"] = f"BUY+2 (MANIP→EXPANSION long P={next_conf:.2f} ctx={ctx_used})"
                elif _phase_code_for_wheel == 2 and next_phase == 3 and next_conf >= 0.60:
                    if structure.get("hh_hl"):
                        secondary_sell += 2.0
                        factors["wheel_transition"] = f"SELL+2 (EXP→DISTRIB P={next_conf:.2f} ctx={ctx_used})"
                    else:
                        secondary_buy += 2.0
                        factors["wheel_transition"] = f"BUY+2 (EXP→DISTRIB low P={next_conf:.2f} ctx={ctx_used})"
                else:
                    factors["wheel_transition"] = (
                        f"INFO {wheel_transition.get('current_phase_name')}"
                        f"→{wheel_transition.get('next_phase_name')} P={next_conf:.2f} ctx={ctx_used}"
                    )
            except Exception as _e:
                factors["wheel_transition"] = f"ERROR ({_e})"
        else:
            factors["wheel_transition"] = "NOT_FITTED (run wheel_trainer.py to fit)"
    else:
        factors["wheel_transition"] = "NONE (phase unknown)"

    # SECONDARY 4 — Order-flow and iceberg absorption
    of_imbalance = float(order_flow.get("flow_imbalance") or 0.0)
    of_side = str(order_flow.get("aggressive_side") or "NEUTRAL").upper()
    iceberg = bool(order_flow.get("iceberg_detected", False))
    iceberg_side = str(order_flow.get("iceberg_side") or "NONE").upper()
    absorption_score = float(order_flow.get("iceberg_absorption_score") or 0.0)

    if iceberg and iceberg_side == "BUY" and absorption_score >= 0.6:
        secondary_buy += 2.0
        factors["order_flow"] = (
            f"BUY+2 (iceberg absorption BUY, score={absorption_score:.2f}, imbalance={of_imbalance:.3f})"
        )
    elif iceberg and iceberg_side == "SELL" and absorption_score >= 0.6:
        secondary_sell += 2.0
        factors["order_flow"] = (
            f"SELL+2 (iceberg absorption SELL, score={absorption_score:.2f}, imbalance={of_imbalance:.3f})"
        )
    elif of_side == "BUY" and of_imbalance >= 0.18:
        secondary_buy += 1.0
        factors["order_flow"] = f"BUY+1 (aggressive buy flow imbalance={of_imbalance:.3f})"
    elif of_side == "SELL" and of_imbalance <= -0.18:
        secondary_sell += 1.0
        factors["order_flow"] = f"SELL+1 (aggressive sell flow imbalance={of_imbalance:.3f})"
    else:
        factors["order_flow"] = (
            f"NONE (side={of_side}, imbalance={of_imbalance:.3f}, iceberg={iceberg_side})"
        )

    # ---- TERTIARY scores (weight 1 each — context filters only) ----
    tertiary_buy  = 0.0
    tertiary_sell = 0.0

    # TERTIARY 1 — AMD IFVG entry signal
    amd_bull = bool(amd.get("amd_bull_entry", False))
    amd_bear = bool(amd.get("amd_bear_entry", False))
    if amd_bull:
        tertiary_buy += 1.0
        factors["amd_ifvg"] = "BUY+1 (AMD IFVG bull entry)"
    elif amd_bear:
        tertiary_sell += 1.0
        factors["amd_ifvg"] = "SELL+1 (AMD IFVG bear entry)"
    else:
        factors["amd_ifvg"] = "NONE"

    # TERTIARY 2 — Elliott wave phase
    wave_phase    = str(ell.get("wave_phase") or "").upper()
    wave_conf     = float(ell.get("wave_confidence") or 0.0)
    wave_up       = bool(ell.get("wave_direction_up", False))
    wave_progress = float(ell.get("wave_progress") or 0.0)
    if wave_phase in {"IMPULSE", "MOTIVE"} and wave_conf >= 0.45:
        if wave_up and wave_progress < 0.75:
            tertiary_buy += 1.0
            factors["elliott"] = f"BUY+1 (impulse up, progress={wave_progress:.2f})"
        elif not wave_up and wave_progress < 0.75:
            tertiary_sell += 1.0
            factors["elliott"] = f"SELL+1 (impulse down, progress={wave_progress:.2f})"
        elif wave_progress >= 0.75:
            if wave_up:
                tertiary_sell += 1.0
                factors["elliott"] = f"SELL+1 (impulse exhausting, progress={wave_progress:.2f})"
            else:
                tertiary_buy += 1.0
                factors["elliott"] = f"BUY+1 (impulse exhausting, progress={wave_progress:.2f})"
        else:
            factors["elliott"] = f"NONE (phase={wave_phase}, conf={wave_conf:.2f})"
    elif wave_phase in {"CORRECTIVE", "CORRECTION"}:
        tertiary_buy += 1.0
        factors["elliott"] = "BUY+1 (correction phase)"
    else:
        factors["elliott"] = f"NONE (phase={wave_phase}, conf={wave_conf:.2f})"

    # TERTIARY 3 — Session kill zone
    london_open = bool(participation.get("london_open", False))
    ny_open     = bool(participation.get("newyork_open", False))
    if london_open or ny_open:
        session_label = "London" if london_open else "NewYork"
        if p_sell > p_buy:
            tertiary_sell += 1.0
            factors["session"] = f"SELL+1 ({session_label} kill zone)"
        else:
            tertiary_buy += 1.0
            factors["session"] = f"BUY+1 ({session_label} kill zone)"
    else:
        factors["session"] = "NONE (no kill zone active)"

    # TERTIARY 4 — Gann major turn window (timing filter only)
    major_turn = bool(obs.get("major_turn_window", False))
    sqrt_deg   = float(obs.get("sqrt_rotation_deg") or 0.0)
    if major_turn:
        if structure.get("hh_hl"):
            tertiary_sell += 1.0
            factors["wheel_turn"] = "SELL+1 (Gann major turn window, uptrend)"
        else:
            tertiary_buy += 1.0
            factors["wheel_turn"] = "BUY+1 (Gann major turn window, downtrend)"
    else:
        factors["wheel_turn"] = f"NONE (sqrt_deg={sqrt_deg:.1f})"

    # TERTIARY 5 — Gann harmonic proximity (reversal timing filter)
    harmonic_near = _near_harmonic(sqrt_deg)
    if harmonic_near:
        tertiary_sell += 1.0
        factors["harmonic"] = f"SELL+1 (Gann harmonic at {sqrt_deg:.1f}°)"
    else:
        factors["harmonic"] = f"NONE ({sqrt_deg:.1f}°)"

    # TERTIARY 6 — Turtle Soup
    turtle_soup = mem.get("turtle_soup") or {}
    ts_bear = bool(turtle_soup.get("turtle_soup_sell", False))
    ts_bull = bool(turtle_soup.get("turtle_soup_buy", False))
    if ts_bear:
        tertiary_sell += 1.0
        factors["turtle_soup"] = f"SELL+1 (turtle soup, sweep_high={turtle_soup.get('sweep_level')})"
    elif ts_bull:
        tertiary_buy += 1.0
        factors["turtle_soup"] = f"BUY+1 (turtle soup, sweep_low={turtle_soup.get('sweep_level')})"
    else:
        factors["turtle_soup"] = "NONE"

    # ---- Aggregate buy/sell totals ----
    buy_score  = primary_buy  + secondary_buy  + tertiary_buy
    sell_score = primary_sell + secondary_sell + tertiary_sell

    factors["_score_breakdown"] = {
        "primary_buy": primary_buy, "primary_sell": primary_sell,
        "secondary_buy": secondary_buy, "secondary_sell": secondary_sell,
        "tertiary_buy": tertiary_buy, "tertiary_sell": tertiary_sell,
    }

    # ------------------------------------------------------------------
    # Regime weight — scales effective threshold
    # ------------------------------------------------------------------
    regime_label: str | None = None
    _regime_weight = 1.0
    if regime_result:
        regime_label = regime_result.get("regime")
        _regime_weight = float(regime_result.get("decision_weight", 1.0))
        factors["regime"] = (
            f"{regime_label} (weight={_regime_weight:.2f}, "
            f"atr_z={regime_result.get('atr_z', 0):.2f})"
        )
    else:
        factors["regime"] = "NOT_PROVIDED"

    # ------------------------------------------------------------------
    # Final verdict — hierarchical gating
    # ------------------------------------------------------------------
    # RULE 1 (PRIMARY GATE): At least one PRIMARY condition must fire in
    # the intended direction.  A non-zero primary score in the OPPOSITE
    # direction is allowed — but the intended direction must have ≥3 pts
    # of PRIMARY support (i.e. at least one PRIMARY factor fired).
    #
    # RULE 2 (REGIME THRESHOLD): Total score must meet regime-adjusted
    # minimum.  TREND market: threshold = 4.0 (easier to confirm);
    # RANGE market: threshold = 6.0 (harder to trade against noise).
    #
    # Thresholds are intentionally higher than the old system (was 3.0)
    # because primary scores are up to ×3 weight — false confluence
    # happens when only tertiary/secondary signals agree.
    # ------------------------------------------------------------------

    # Regime-adjusted threshold (default 5.0 — requires at least primary+secondary)
    _base_threshold = 5.0
    _effective_threshold = _base_threshold / _regime_weight

    skip_reason: str | None = None
    direction: str = "WAIT"

    if buy_score > sell_score:
        # PRIMARY gate: BOTH phase AND liquidity must fire in the same direction
        # Phase alone = 3 pts; Liquidity alone = 3 pts; Both = 6 pts.
        # Requiring ≥6 ensures neither condition alone is sufficient to trade.
        if primary_buy < 6.0:
            direction = "WAIT"
            skip_reason = (
                f"primary_gate_fail (BUY: primary_buy={primary_buy:.0f}, "
                f"need≥6 — phase AND liquidity sweep must both confirm)"
            )
        elif buy_score >= _effective_threshold:
            direction = "BUY"
        else:
            direction = "WAIT"
            skip_reason = (
                f"low_confluence (buy={buy_score:.1f}, "
                f"need≥{_effective_threshold:.1f}, regime={regime_label or 'n/a'})"
            )
    elif sell_score > buy_score:
        # PRIMARY gate: BOTH phase AND liquidity must fire for SELL
        if primary_sell < 6.0:
            direction = "WAIT"
            skip_reason = (
                f"primary_gate_fail (SELL: primary_sell={primary_sell:.0f}, "
                f"need≥6 — phase AND liquidity sweep must both confirm)"
            )
        elif sell_score >= _effective_threshold:
            direction = "SELL"
        else:
            direction = "WAIT"
            skip_reason = (
                f"low_confluence (sell={sell_score:.1f}, "
                f"need≥{_effective_threshold:.1f}, regime={regime_label or 'n/a'})"
            )
    else:
        direction = "WAIT"
        skip_reason = f"tied_scores (buy={buy_score:.1f}, sell={sell_score:.1f})"

    confluence_score = max(buy_score, sell_score)
    confidence = min(1.0, confluence_score / 10.0)   # max possible ~10 (primary+secondary+tertiary)

    # ------------------------------------------------------------------
    # SL / TP guidance from location context
    # ------------------------------------------------------------------
    price = float(state.get("price") or 0.0)
    avg_range = 0.0
    bar = mem.get("bar") or {}
    if bar.get("high") and bar.get("low"):
        avg_range = abs(float(bar["high"]) - float(bar["low"]))

    sl_zone: float | None = None
    tp_zone: float | None = None

    if direction == "SELL" and price > 0:
        # SL = above recent equal highs / sweep level
        eq_high = location.get("equal_highs_near")
        sweep_lvl = float(turtle_soup.get("sweep_level") or 0.0)
        sl_zone = max(
            price + max(avg_range * 1.2, price * 0.003),
            (sweep_lvl if sweep_lvl > price else 0) or (price + avg_range * 1.5),
        )
        tp_zone = price - avg_range * 3.0

    elif direction == "BUY" and price > 0:
        eq_low = location.get("equal_lows_near")
        sweep_lvl = float(turtle_soup.get("sweep_level") or 0.0)
        sl_zone = min(
            price - max(avg_range * 1.2, price * 0.003),
            (sweep_lvl if sweep_lvl < price else float("inf")) or (price - avg_range * 1.5),
        )
        tp_zone = price + avg_range * 3.0

    return {
        "direction": direction,
        "confidence": round(confidence, 4),
        "confluence_score": confluence_score,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "skip_reason": skip_reason,
        "sl_zone": round(sl_zone, 2) if sl_zone else None,
        "tp_zone": round(tp_zone, 2) if tp_zone else None,
        "price": price,
        "wheel_transition": wheel_transition,
        "regime": regime_label,
        "regime_weight": _regime_weight,
        "factor_breakdown": factors,
    }
