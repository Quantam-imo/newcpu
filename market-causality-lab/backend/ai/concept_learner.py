from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_STATE_PATH = Path("data/ai_models/concept_reasoning_state.json")
_HARMONIC_DEGREES = (0.0, 45.0, 72.0, 90.0, 120.0, 144.0, 180.0, 216.0, 240.0, 270.0, 315.0, 360.0)


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default


def _utc_iso(ts: Any) -> str:
    if ts is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        if hasattr(ts, "to_pydatetime"):
            dt = ts.to_pydatetime()
        elif isinstance(ts, datetime):
            dt = ts
        else:
            return str(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except Exception:
        return datetime.now(timezone.utc).isoformat()


def _circular_distance(a_deg: float, b_deg: float) -> float:
    return abs(((a_deg - b_deg + 180.0) % 360.0) - 180.0)


def _near_harmonic(deg: float, tol: float = 12.0) -> bool:
    d = _safe_float(deg)
    return any(_circular_distance(d, h) <= tol for h in _HARMONIC_DEGREES)


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.exists():
        return {
            "version": 1,
            "meta": {"updates": 0, "last_update": None},
            "pending": None,
            "concept_stats": {},
        }
    try:
        data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid_state_type")
        data.setdefault("version", 1)
        data.setdefault("meta", {"updates": 0, "last_update": None})
        data.setdefault("pending", None)
        data.setdefault("concept_stats", {})
        return data
    except Exception:
        return {
            "version": 1,
            "meta": {"updates": 0, "last_update": None},
            "pending": None,
            "concept_stats": {},
        }


def _save_state(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _ensure_bucket(state: dict[str, Any], concept: str, direction: str) -> dict[str, float]:
    stats = state.setdefault("concept_stats", {})
    c = stats.setdefault(concept, {})
    d = c.setdefault(direction, {"tp": 0.0, "fp": 0.0, "neutral": 0.0})
    d.setdefault("tp", 0.0)
    d.setdefault("fp", 0.0)
    d.setdefault("neutral", 0.0)
    return d


def _extract_concepts(
    record: dict[str, Any] | None,
    regime_result: dict[str, Any] | None,
    confluence: dict[str, Any] | None,
    astro: dict[str, Any] | None,
    gann_adv: dict[str, Any] | None,
) -> list[str]:
    rec = record or {}
    concepts: set[str] = set()

    phase = str(rec.get("phase") or "").upper().strip()
    if phase:
        concepts.add(f"phase:{phase}")

    liq = str((rec.get("liquidity") or {}).get("type") or "NONE").upper().strip()
    concepts.add(f"liquidity:{liq}")
    if liq in {"BUY_SIDE_SWEEP", "SELL_SIDE_SWEEP"}:
        concepts.add("liquidity:SWEEP")

    structure_up = bool((rec.get("structure") or {}).get("hh_hl", False))
    concepts.add("structure:UP" if structure_up else "structure:DOWN")

    order_flow = rec.get("order_flow") or {}
    of_side = str(order_flow.get("aggressive_side") or "NEUTRAL").upper().strip()
    if of_side in {"BUY", "SELL"}:
        concepts.add(f"orderflow:AGGRESSIVE_{of_side}")
    of_imb = _safe_float(order_flow.get("flow_imbalance"), 0.0)
    if of_imb >= 0.18:
        concepts.add("orderflow:IMBALANCE_BUY")
    elif of_imb <= -0.18:
        concepts.add("orderflow:IMBALANCE_SELL")
    if bool(order_flow.get("iceberg_detected", False)):
        side = str(order_flow.get("iceberg_side") or "NONE").upper().strip()
        if side in {"BUY", "SELL"}:
            concepts.add(f"orderflow:ICEBERG_{side}")

    gam = rec.get("gann_astro_math") or {}
    if bool(gam.get("major_turn_window", False)):
        concepts.add("gann:MAJOR_TURN")
    sqrt_deg = _safe_float(gam.get("sqrt_rotation_deg"), 0.0)
    if _near_harmonic(sqrt_deg):
        concepts.add("gann:HARMONIC_NEAR")

    if gann_adv:
        degree = _safe_float(gann_adv.get("degree"), 0.0)
        concepts.add(f"gann_adv:DEG_BIN_{int(degree // 30) * 30}")
        if bool(gann_adv.get("price_time_equal", False)):
            concepts.add("gann_adv:PRICE_TIME_EQUAL")
        zone = str(gann_adv.get("zone") or "").upper().strip()
        if zone:
            concepts.add(f"gann_adv:ZONE_{zone}")

    news = rec.get("news") or {}
    if bool(news.get("high_impact_active", False)):
        concepts.add("news:HIGH_IMPACT")
    if _safe_float(news.get("event_count"), 0.0) > 0:
        concepts.add("news:EVENT_ACTIVE")
    if _safe_float(news.get("gann_event_count"), 0.0) > 0:
        concepts.add("news:GANN_EVENT")
    if _safe_float(news.get("nakshatra_event_count"), 0.0) > 0:
        concepts.add("news:NAKSHATRA_EVENT")
    if _safe_float(news.get("aspect_event_count"), 0.0) > 0:
        concepts.add("news:ASPECT_EVENT")

    if astro:
        strength = str(astro.get("strength") or "").upper().strip()
        if strength:
            concepts.add(f"astro:STRENGTH_{strength}")
        moon_key = str((astro.get("moon") or {}).get("phase_key") or "").upper().strip()
        if moon_key:
            concepts.add(f"astro:MOON_{moon_key}")
        ev = astro.get("nearby_event") or {}
        impact = str(ev.get("impact_level") or "").upper().strip()
        if impact:
            concepts.add(f"astro:EVENT_IMPACT_{impact}")
        exp_dir = str(ev.get("expected_direction") or "").upper().strip()
        if exp_dir in {"BUY", "SELL", "BULLISH", "BEARISH", "UP", "DOWN"}:
            concepts.add(f"astro:EXPECTED_{exp_dir}")

    if regime_result:
        regime = str(regime_result.get("regime") or "").upper().strip()
        if regime:
            concepts.add(f"regime:{regime}")
        atr_z = _safe_float(regime_result.get("atr_z"), 0.0)
        if atr_z > 1.5:
            concepts.add("volatility:HIGH")
        elif atr_z < 0.5:
            concepts.add("volatility:LOW")
        else:
            concepts.add("volatility:MED")

    factors = (confluence or {}).get("factor_breakdown") or {}
    for k in ("phase_primary", "liquidity_primary", "model", "ict_trigger", "wheel_transition", "elliott", "session", "harmonic", "turtle_soup", "amd_ifvg"):
        msg = str(factors.get(k) or "")
        if "BUY+" in msg:
            concepts.add(f"factor:{k}:BUY")
        elif "SELL+" in msg:
            concepts.add(f"factor:{k}:SELL")

    return sorted(concepts)


def _resolve_previous(state: dict[str, Any], current_price: float, move_threshold_pct: float) -> dict[str, Any]:
    pending = state.get("pending")
    if not isinstance(pending, dict):
        return {"resolved": False, "reason": "no_pending"}

    prev_price = _safe_float(pending.get("price"), 0.0)
    prev_dir = str(pending.get("direction") or "WAIT").upper().strip()
    concepts = pending.get("concepts") or []

    if prev_price <= 0.0 or current_price <= 0.0 or prev_dir not in {"BUY", "SELL"}:
        state["pending"] = None
        return {"resolved": False, "reason": "invalid_pending"}

    ret = (current_price - prev_price) / prev_price
    if abs(ret) < move_threshold_pct:
        actual = "WAIT"
    else:
        actual = "BUY" if ret > 0 else "SELL"

    for c in concepts:
        b = _ensure_bucket(state, str(c), prev_dir)
        if actual == "WAIT":
            b["neutral"] += 1.0
        elif actual == prev_dir:
            b["tp"] += 1.0
        else:
            b["fp"] += 1.0

    state["pending"] = None
    state.setdefault("meta", {}).setdefault("updates", 0)
    state["meta"]["updates"] = int(state["meta"]["updates"] or 0) + 1
    state["meta"]["last_update"] = datetime.now(timezone.utc).isoformat()

    return {
        "resolved": True,
        "predicted": prev_dir,
        "actual": actual,
        "return_pct": round(ret * 100.0, 5),
        "concepts_used": len(concepts),
    }


def _score_direction(state: dict[str, Any], direction: str, concepts: list[str]) -> dict[str, Any]:
    d = str(direction or "WAIT").upper().strip()
    if d not in {"BUY", "SELL"}:
        return {
            "direction": d,
            "score": None,
            "effective_samples": 0.0,
            "supporting": [],
            "opposing": [],
        }

    contributions: list[tuple[str, float, float]] = []
    total = 0.0
    samples = 0.0
    stats = state.get("concept_stats") or {}

    for c in concepts:
        row = ((stats.get(c) or {}).get(d) or {})
        tp = _safe_float(row.get("tp"), 0.0)
        fp = _safe_float(row.get("fp"), 0.0)
        n = tp + fp
        if n <= 0:
            continue
        # Beta-smoothed success estimate and confidence weight by sample size.
        p = (tp + 1.0) / (tp + fp + 2.0)
        edge = p - 0.5
        w = min(1.0, n / 20.0)
        contrib = edge * w
        contributions.append((c, contrib, n))
        total += contrib
        samples += n

    if not contributions:
        return {
            "direction": d,
            "score": 0.5,
            "effective_samples": 0.0,
            "supporting": [],
            "opposing": [],
        }

    norm = max(1.0, float(len(contributions)))
    score = 0.5 + (total / norm)
    score = max(0.05, min(0.95, score))

    supporting = [
        {"concept": c, "contribution": round(v, 5), "samples": int(n)}
        for c, v, n in sorted(contributions, key=lambda x: x[1], reverse=True)
        if v > 0
    ][:5]
    opposing = [
        {"concept": c, "contribution": round(v, 5), "samples": int(n)}
        for c, v, n in sorted(contributions, key=lambda x: x[1])
        if v < 0
    ][:5]

    return {
        "direction": d,
        "score": round(float(score), 5),
        "effective_samples": round(float(samples), 2),
        "supporting": supporting,
        "opposing": opposing,
    }


def concept_learning_step(
    direction: str,
    current_price: float,
    current_ts: Any,
    record: dict[str, Any] | None,
    regime_result: dict[str, Any] | None,
    confluence: dict[str, Any] | None,
    astro: dict[str, Any] | None,
    gann_adv: dict[str, Any] | None,
    move_threshold_pct: float = 0.00035,
) -> dict[str, Any]:
    """
    Self-learning step:
      1) resolves previous pending prediction using realized move on current bar,
      2) updates per-concept causal stats,
      3) scores current direction from learned concept history,
      4) stores current prediction as pending for next bar resolution.

    move_threshold_pct default 0.035% avoids noisy micro-moves becoming labels.
    """
    state = _load_state()

    resolved = _resolve_previous(state, _safe_float(current_price, 0.0), move_threshold_pct)
    concepts = _extract_concepts(record, regime_result, confluence, astro, gann_adv)
    scoring = _score_direction(state, direction, concepts)

    d = str(direction or "WAIT").upper().strip()
    registered = False
    if d in {"BUY", "SELL"} and _safe_float(current_price, 0.0) > 0.0:
        state["pending"] = {
            "timestamp": _utc_iso(current_ts),
            "direction": d,
            "price": round(_safe_float(current_price, 0.0), 8),
            "concepts": concepts,
        }
        registered = True
    else:
        state["pending"] = None

    _save_state(state)

    return {
        "resolved_previous": resolved,
        "current_scoring": scoring,
        "registered_pending": registered,
        "concept_count": len(concepts),
        "state_path": str(_STATE_PATH),
        "meta": state.get("meta", {}),
    }
