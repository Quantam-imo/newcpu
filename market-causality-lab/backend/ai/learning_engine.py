from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_JOURNAL_DB = Path("ai_trade_journal.db")
_CONFIDENCE_WEIGHTS_PATH = Path("data/ai_models/confidence_weights.json")


# ---------------------------------------------------------------------------
# Legacy helper (kept for any callers that still use it)
# ---------------------------------------------------------------------------

def learning_engine(prediction: str, actual: str, weights: dict) -> dict:
    """Simple reward/penalty weight update. Legacy interface."""
    reward = 1 if prediction == actual else -1
    for k in weights:
        weights[k] += 0.1 * reward
    return weights


# ---------------------------------------------------------------------------
# Journal-backed learning: read closed trades → update bundle confidence
# ---------------------------------------------------------------------------

def load_confidence_weights() -> dict[str, float]:
    """Load per-scope confidence adjustment weights (±0.0–1.0 scale)."""
    if not _CONFIDENCE_WEIGHTS_PATH.exists():
        return {}
    try:
        data = json.loads(_CONFIDENCE_WEIGHTS_PATH.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_confidence_weights(weights: dict[str, float]) -> None:
    _CONFIDENCE_WEIGHTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIDENCE_WEIGHTS_PATH.write_text(json.dumps(weights, indent=2), encoding="utf-8")


def record_trade_outcome(
    scope: str,
    direction: str,
    confidence: float,
    result: str,       # "WIN" | "LOSS" | "BREAKEVEN"
    r_multiple: float,
    pnl: float,
    entry_price: float,
    sl: float,
    tp: float,
    exit_price: float,
    session: str = "",
    narrative: str = "",
) -> None:
    """
    Write a closed trade to the journal DB and update confidence weights.
    Call this from your live-trading layer when a trade closes.
    """
    try:
        conn = sqlite3.connect(str(_JOURNAL_DB))
        conn.execute(
            """INSERT INTO trades
               (timestamp, symbol, model, entry_reason, rr, entry_price, sl, tp,
                exit_price, result, r_multiple, pnl, confidence, session, narrative)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                datetime.now(timezone.utc).isoformat(),
                "XAUUSD",
                scope,
                direction,
                (tp - entry_price) / max(1e-9, abs(entry_price - sl)) if entry_price and sl and tp else 0.0,
                entry_price, sl, tp, exit_price,
                result, r_multiple, pnl, confidence,
                session, narrative,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Update running confidence weight for this scope
    _update_confidence_weight(scope, result, r_multiple)


def _update_confidence_weight(scope: str, result: str, r_multiple: float) -> None:
    """
    Adjust per-scope confidence weight based on trade outcome.
    WIN  → weight nudges up   (max 1.5)
    LOSS → weight nudges down (min 0.3)
    Applied as a multiplier to model p_buy/p_sell at serving time.
    """
    weights = load_confidence_weights()
    current = float(weights.get(scope, 1.0))

    if result == "WIN":
        delta = 0.05 * max(0.5, min(3.0, r_multiple))
        current = min(1.5, current + delta)
    elif result == "LOSS":
        delta = 0.04 * max(0.5, min(3.0, abs(r_multiple)))
        current = max(0.3, current - delta)
    # BREAKEVEN: no change

    weights[scope] = round(current, 4)
    save_confidence_weights(weights)


def get_scope_performance_summary(scope: str | None = None) -> dict[str, Any]:
    """
    Query the trade journal for win rate, avg R and total trades per scope.
    If scope is None, returns aggregate across all scopes.
    """
    if not _JOURNAL_DB.exists():
        return {"error": "journal_db_not_found"}
    try:
        conn = sqlite3.connect(str(_JOURNAL_DB))
        if scope:
            rows = conn.execute(
                "SELECT result, r_multiple, pnl, confidence FROM trades WHERE model=?",
                (scope,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT result, r_multiple, pnl, confidence FROM trades"
            ).fetchall()
        conn.close()
    except Exception as exc:
        return {"error": str(exc)}

    if not rows:
        return {"trades": 0, "scope": scope}

    total = len(rows)
    wins = sum(1 for r in rows if r[0] == "WIN")
    losses = sum(1 for r in rows if r[0] == "LOSS")
    avg_r = sum(float(r[1] or 0) for r in rows) / max(1, total)
    total_pnl = sum(float(r[2] or 0) for r in rows)
    avg_conf = sum(float(r[3] or 0) for r in rows) / max(1, total)
    win_rate = wins / max(1, total)

    return {
        "scope": scope or "all",
        "trades": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "avg_r_multiple": round(avg_r, 4),
        "total_pnl": round(total_pnl, 4),
        "avg_confidence": round(avg_conf, 4),
        "confidence_weight": round(load_confidence_weights().get(scope or "", 1.0), 4),
    }


def apply_confidence_weight(scope: str, p_buy: float) -> float:
    """
    Apply the per-scope learned confidence weight to the raw model probability.
    p_buy_adjusted = clip(p_buy * weight, 0.05, 0.95)
    Call this in serving.py after getting p_buy from the model.
    """
    weights = load_confidence_weights()
    w = float(weights.get(scope, 1.0))
    # Apply weight symmetrically around 0.5
    adjusted = 0.5 + (p_buy - 0.5) * w
    return float(max(0.05, min(0.95, adjusted)))
