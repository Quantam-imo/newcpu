"""
Backtest Replay Loop — AstroQuant MCL Learning Engine

Loads historical OHLCV data from saved chart files, simulates directional
predictions using a minimal trend-following ruleset, evaluates each prediction
using forward price realisation, then feeds every (prediction, outcome) pair to
LearningFeedbackEngine so the signal weights accumulate real calibration.

Usage:
    python -m astroquant.backend.backtest_replay
    python -m astroquant.backend.backtest_replay --symbol GC.FUT --timeframe 5m --window 12 --horizon 24

Arguments:
    --symbol    SYMBOL.FUT prefix to match chart files (default: GC.FUT)
    --timeframe timeframe suffix to match chart files (default: 5m)
    --window    lookback bars for trend signal (default: 12)
    --horizon   forward bars to evaluate outcome (default: 24)
    --dry-run   print actions without writing to tracker
    --min-move  minimum absolute pip move to count as directional (default: 3.0)

Philosophy (W.D. Gann):
    "The market never lies — only our interpretation of it does.
     Replay teaches humility; calibration teaches precision."
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_log = logging.getLogger("backtest_replay")

# ── project path setup ────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
sys.path.insert(0, str(_ROOT))

from astroquant.backend.mathematical_engines import LearningFeedbackEngine  # noqa: E402
from astroquant.backend.prediction_tracker import PredictionTracker         # noqa: E402

_DATA_DIR = _ROOT / "data"


# ── candle helpers ────────────────────────────────────────────────────────────

def _load_candles(symbol: str, timeframe: str) -> list[dict[str, Any]]:
    """Load OHLCV bars from the best matching chart file under data/."""
    pattern = f"last_known_chart_{symbol}_{timeframe}.json"
    candidates = sorted(_DATA_DIR.glob(f"last_known_chart_{symbol}*_{timeframe}*.json"))
    if not candidates:
        # Try without extension suffix (e.g. _5 instead of _5m)
        tf_short = timeframe.rstrip("m").rstrip("h").rstrip("d")
        candidates = sorted(_DATA_DIR.glob(f"last_known_chart_{symbol}*_{tf_short}*.json"))
    if not candidates:
        raise FileNotFoundError(
            f"No chart file found for symbol={symbol} timeframe={timeframe} in {_DATA_DIR}"
        )
    chosen = candidates[-1]
    _log.info("Loading candles from: %s", chosen.name)
    with chosen.open() as fh:
        raw = json.load(fh)
    candles = raw if isinstance(raw, list) else raw.get("candles", raw.get("bars", raw.get("ohlcv", [])))
    if not candles:
        raise ValueError(f"No OHLCV data found in {chosen}")
    _log.info("Loaded %d bars from %s", len(candles), chosen.name)
    return candles


def _bar_close(bar: dict[str, Any]) -> float:
    return float(bar.get("close") or bar.get("c") or 0.0)


def _bar_high(bar: dict[str, Any]) -> float:
    return float(bar.get("high") or bar.get("h") or _bar_close(bar))


def _bar_low(bar: dict[str, Any]) -> float:
    return float(bar.get("low") or bar.get("l") or _bar_close(bar))


def _bar_ts(bar: dict[str, Any]) -> str:
    return str(bar.get("timestamp") or bar.get("time") or "unknown")


# ── signal generation ─────────────────────────────────────────────────────────

def _generate_signal(bars: list[dict[str, Any]], idx: int, window: int) -> tuple[str, float, bool, bool, bool, bool, bool, bool]:
    """
    Derive a directional signal from the previous `window` bars ending at idx-1.

    Returns:
        (direction, confluence_score,
         geometry_signal, time_signal, structure_signal,
         momentum_signal, gann_signal, ict_signal)

    Signal rule (minimal Gann-inspired):
    - Short MA  = mean close of last window//3 bars
    - Long  MA  = mean close of last window bars
    - BUY  if short > long by >0.05% (uptrend)
    - SELL if short < long by >0.05% (downtrend)
    - WAIT otherwise
    """
    start = max(0, idx - window)
    segment = bars[start:idx]
    if len(segment) < 3:
        return "WAIT", 0.1, False, False, False, False, False, False

    closes = [_bar_close(b) for b in segment]
    short_n = max(1, window // 3)
    short_ma = sum(closes[-short_n:]) / short_n
    long_ma = sum(closes) / len(closes)

    if long_ma <= 0:
        return "WAIT", 0.1, False, False, False, False, False, False

    diff_pct = (short_ma - long_ma) / long_ma

    # Momentum: consecutive up/down bars
    last3 = closes[-3:]
    momentum_up = all(last3[i] < last3[i + 1] for i in range(len(last3) - 1))
    momentum_down = all(last3[i] > last3[i + 1] for i in range(len(last3) - 1))

    # Structure: recent swing high/low
    highs = [_bar_high(b) for b in segment]
    lows  = [_bar_low(b) for b in segment]
    mid = len(highs) // 2
    struct_bull = max(highs[mid:]) > max(highs[:mid]) and min(lows[mid:]) > min(lows[:mid])
    struct_bear = max(highs[mid:]) < max(highs[:mid]) and min(lows[mid:]) < min(lows[:mid])

    if diff_pct > 0.0005:
        direction = "BUY"
        geometry_signal   = True
        time_signal       = struct_bull
        structure_signal  = struct_bull
        momentum_signal   = momentum_up
        gann_signal       = abs(diff_pct) > 0.001
        ict_signal        = momentum_up and struct_bull
        score_parts = [geometry_signal, time_signal, structure_signal, momentum_signal, gann_signal, ict_signal]
        confluence_score  = round(sum(score_parts) / len(score_parts), 3)

    elif diff_pct < -0.0005:
        direction = "SELL"
        geometry_signal   = True
        time_signal       = struct_bear
        structure_signal  = struct_bear
        momentum_signal   = momentum_down
        gann_signal       = abs(diff_pct) > 0.001
        ict_signal        = momentum_down and struct_bear
        score_parts = [geometry_signal, time_signal, structure_signal, momentum_signal, gann_signal, ict_signal]
        confluence_score  = round(sum(score_parts) / len(score_parts), 3)

    else:
        direction = "WAIT"
        geometry_signal = time_signal = structure_signal = False
        momentum_signal = gann_signal = ict_signal = False
        confluence_score = 0.1

    return (direction, confluence_score,
            geometry_signal, time_signal, structure_signal,
            momentum_signal, gann_signal, ict_signal)


# ── outcome evaluation ────────────────────────────────────────────────────────

def _evaluate_outcome(
    bars: list[dict[str, Any]],
    entry_idx: int,
    entry_price: float,
    horizon: int,
    min_move: float,
) -> tuple[str, float, float, int]:
    """
    Look forward `horizon` bars from entry_idx to determine what actually happened.

    Returns:
        (outcome_direction, realized_price, actual_move_pips, bars_to_outcome)
    """
    end_idx = min(len(bars) - 1, entry_idx + horizon)
    future_bars = bars[entry_idx + 1 : end_idx + 1]

    if not future_bars:
        return "SIDEWAYS", entry_price, 0.0, 0

    # High/low/final within horizon
    all_closes = [_bar_close(b) for b in future_bars]
    max_high = max(_bar_high(b) for b in future_bars)
    min_low  = min(_bar_low(b) for b in future_bars)

    move_up   = max_high - entry_price
    move_down = entry_price - min_low
    final_px  = all_closes[-1]
    net_move  = final_px - entry_price

    if abs(net_move) < min_move:
        outcome_direction = "SIDEWAYS"
        realized_price    = final_px
        actual_move_pips  = abs(net_move)
        bars_taken        = len(future_bars)
    elif net_move > 0:
        # Find first bar that made a significant up move
        bars_taken = next(
            (i + 1 for i, b in enumerate(future_bars) if _bar_high(b) - entry_price >= min_move),
            len(future_bars),
        )
        outcome_direction = "UP"
        realized_price    = entry_price + move_up
        actual_move_pips  = move_up
    else:
        bars_taken = next(
            (i + 1 for i, b in enumerate(future_bars) if entry_price - _bar_low(b) >= min_move),
            len(future_bars),
        )
        outcome_direction = "DOWN"
        realized_price    = entry_price - move_down
        actual_move_pips  = move_down

    return outcome_direction, realized_price, actual_move_pips, bars_taken


# ── main replay loop ──────────────────────────────────────────────────────────

def run_replay(
    symbol: str = "GC.FUT",
    timeframe: str = "5m",
    window: int = 12,
    horizon: int = 24,
    min_move: float = 3.0,
    dry_run: bool = False,
    tracker_path: str | None = None,
) -> dict[str, Any]:
    """
    Run a full backtest replay and feed every (prediction, outcome) pair into
    the LearningFeedbackEngine.

    Returns:
        Summary dict with total/correct/accuracy + weight updates.
    """
    candles = _load_candles(symbol, timeframe)

    tracker = PredictionTracker(tracker_path)
    # Don't bind the real tracker to the engine during dry_run:
    # LearningFeedbackEngine.__init__ replays existing outcomes which calls
    # save_weights() — that would mutate persisted state even for dry runs.
    engine  = LearningFeedbackEngine(tracker=tracker if not dry_run else None)

    total = 0
    correct = 0
    skipped = 0
    wait_count = 0
    errors: list[str] = []

    # Forecast horizon in days: rough approximation
    # Normalise before lookup so bare TFs like "1", "5" map correctly.
    tf_minutes = {
        "1m": 1, "5m": 5, "15m": 15, "30m": 30,
        "1h": 60, "4h": 240, "1d": 1440,
    }.get(_normalize_timeframe(timeframe), 5)
    horizon_days = max(1, round(horizon * tf_minutes / 1440))

    # Stride: don't overlap prediction windows
    stride = max(1, horizon // 2)

    for idx in range(window, len(candles) - horizon, stride):
        bar         = candles[idx]
        entry_price = _bar_close(bar)
        bar_ts      = _bar_ts(bar)

        if entry_price <= 0:
            skipped += 1
            continue

        (direction, confluence_score,
         geom, time_s, struct, momentum, gann, ict) = _generate_signal(candles, idx, window)

        if direction == "WAIT":
            wait_count += 1
            continue

        # Derive stop/target from average recent ATR
        recent_highs = [_bar_high(candles[i]) for i in range(max(0, idx - window), idx)]
        recent_lows  = [_bar_low(candles[i])  for i in range(max(0, idx - window), idx)]
        atr_est = max(1.0, (sum(h - l for h, l in zip(recent_highs, recent_lows)) / max(1, len(recent_highs))))
        stop_price   = entry_price - atr_est * 1.5 if direction == "BUY" else entry_price + atr_est * 1.5
        target_price = entry_price + atr_est * 3.0 if direction == "BUY" else entry_price - atr_est * 3.0

        # Normalise timeframe in the ID so "1" and "1m" produce the same key,
        # enabling correct upsert/dedup in the tracker across naming conventions.
        prediction_id = f"replay-{symbol}-{_normalize_timeframe(timeframe)}-bar{idx}"

        # Evaluate what actually happened
        outcome_direction, realized_price, actual_move_pips, bars_taken = _evaluate_outcome(
            candles, idx, entry_price, horizon, min_move
        )

        # Determine correctness
        was_correct = (
            (direction == "BUY"  and outcome_direction == "UP")   or
            (direction == "SELL" and outcome_direction == "DOWN")
        )

        _log.debug(
            "bar=%d ts=%s entry=%.2f dir=%s outcome=%s correct=%s",
            idx, bar_ts, entry_price, direction, outcome_direction, was_correct,
        )

        if dry_run:
            total += 1
            if was_correct:
                correct += 1
            continue

        try:
            engine.record_prediction(
                prediction_id         = prediction_id,
                direction             = direction,
                confluence_score      = confluence_score,
                geometry_signal       = geom,
                time_signal           = time_s,
                structure_signal      = struct,
                momentum_signal       = momentum,
                gann_signal           = gann,
                ict_signal            = ict,
                confluence_signal     = confluence_score >= 0.7,
                entry_price           = entry_price,
                stop_price            = stop_price,
                target_price          = target_price,
                forecast_horizon_days = horizon_days,
            )
            engine.record_outcome(
                prediction_id      = prediction_id,
                realized_price     = realized_price,
                outcome_direction  = outcome_direction,
                actual_move_pips   = actual_move_pips,
                timeframe_reached  = bars_taken,
            )
            total += 1
            if was_correct:
                correct += 1
        except Exception as exc:
            errors.append(f"bar={idx}: {exc}")
            _log.warning("Error on bar %d: %s", idx, exc)

    accuracy = round(correct / total * 100, 2) if total else 0.0
    weights  = engine.weights if not dry_run else {}

    summary = {
        "status": "ok" if not errors else "partial",
        "dry_run": dry_run,
        "symbol": symbol,
        "timeframe": timeframe,
        "candles_loaded": len(candles),
        "predictions_evaluated": total,
        "correct": correct,
        "wait_skipped": wait_count,
        "data_skipped": skipped,
        "accuracy_pct": accuracy,
        "errors": errors[:10],
        "learned_weights": weights,
    }

    _log.info(
        "Replay complete: %d predictions | %d correct | %.1f%% accuracy | %d WAIT skipped",
        total, correct, accuracy, wait_count,
    )
    return summary


# ── batch replay ─────────────────────────────────────────────────────────────

def _normalize_timeframe(tf: str) -> str:
    """Normalize bare-number timeframes to minute-suffixed form.

    ``"1"`` → ``"1m"``, ``"5"`` → ``"5m"``, ``"15"`` → ``"15m"`` etc.
    Already-suffixed strings (``"1m"``, ``"1h"``, ``"1d"``) pass through unchanged.
    """
    if tf.isdigit():
        return tf + "m"
    return tf


def _discover_chart_files() -> list[tuple[str, str]]:
    """Return unique (symbol, raw_timeframe) pairs for all last_known_chart_*.json files.

    Bare-number timeframes (``"1"``, ``"5"``) are normalised to minute-suffixed
    form only for deduplication purposes.  The raw timeframe string is kept in
    the returned pair so ``_load_candles`` can still locate the correct file.
    When two files map to the same normalised key (e.g. ``GC.FUT_1.json`` and
    ``GC.FUT_1m.json`` both → ``(GC.FUT, 1m)``), only the first alphabetical
    match is used and the second is skipped with a warning.
    """
    seen: set[tuple[str, str]] = set()   # normalised keys
    pairs: list[tuple[str, str]] = []
    for path in sorted(_DATA_DIR.glob("last_known_chart_*.json")):
        stem = path.stem  # e.g. "last_known_chart_GC.FUT_5m"
        rest = stem[len("last_known_chart_"):]  # e.g. "GC.FUT_5m"
        symbol, _, timeframe = rest.rpartition("_")
        if not symbol or not timeframe:
            continue
        norm_key = (symbol, _normalize_timeframe(timeframe))
        if norm_key in seen:
            _log.warning("Skipping duplicate chart file: %s", path.name)
            continue
        seen.add(norm_key)
        pairs.append((symbol, timeframe))  # keep raw for _load_candles
    return pairs


def _cleanup_bare_ids(tracker: "PredictionTracker") -> int:
    """Rename any predictions/outcomes that use bare-number TF IDs to normalised form.

    For example, ``replay-GC.FUT-1-bar24`` → ``replay-GC.FUT-1m-bar24``.
    Collisions (where the normalised ID already exists) are resolved by keeping
    the normalised entry and dropping the bare one.

    Returns the number of IDs that were renamed or removed.
    """
    import re as _re

    # Matches "replay-<symbol>-<bare_digits>-bar<n>" only when TF has no 'm' suffix.
    _REPLAY_TF_PAT = _re.compile(r"^(replay-.+?-)(\d+)(-bar\d+)$")

    def _fix(pid: str) -> str:
        m = _REPLAY_TF_PAT.match(pid)
        return m.group(1) + m.group(2) + "m" + m.group(3) if m else pid

    preds    = tracker.load_predictions()
    outcomes = tracker.load_outcomes()

    existing_ids = {p["id"] for p in preds}
    changed = 0
    new_preds: list[dict] = []
    id_remap: dict[str, str] = {}  # old_bare_id -> new_normalised_id

    for p in preds:
        fixed = _fix(p["id"])
        if fixed == p["id"]:
            new_preds.append(p)
            continue
        changed += 1
        id_remap[p["id"]] = fixed
        if fixed in existing_ids:
            # Normalised version already exists — drop the bare duplicate
            _log.debug("Dropped bare-TF duplicate: %s (kept %s)", p["id"], fixed)
        else:
            p = dict(p)
            old_id = p["id"]
            p["id"] = fixed
            existing_ids.add(fixed)
            existing_ids.discard(old_id)
            new_preds.append(p)
            _log.debug("Renamed bare-TF ID: %s → %s", old_id, fixed)

    # Remap outcome prediction_id references; deduplicate if collision
    new_outcomes: list[dict] = []
    seen_outcome_ids: set[str] = set()
    for o in outcomes:
        pid = o.get("prediction_id", "")
        new_pid = id_remap.get(pid, pid)
        if new_pid in seen_outcome_ids:
            changed += 1  # dropped bare duplicate outcome
            continue
        seen_outcome_ids.add(new_pid)
        if new_pid != pid:
            o = dict(o)
            o["prediction_id"] = new_pid
        new_outcomes.append(o)

    if changed:
        tracker.save_predictions_bulk(new_preds)
        tracker.save_outcomes_bulk(new_outcomes)
        _log.info("_cleanup_bare_ids: %d IDs cleaned", changed)

    return changed


def run_batch_replay(
    window: int = 12,
    horizon: int = 24,
    min_move: float = 3.0,
    dry_run: bool = False,
    tracker_path: str | None = None,
) -> dict[str, Any]:
    """
    Auto-discover all last_known_chart_*.json files and run run_replay() for
    each (symbol, timeframe) pair, accumulating weight calibration across the
    full dataset library.

    Returns a batch summary dict with per-file results and aggregate stats.
    """
    pairs = _discover_chart_files()
    if not pairs:
        return {"status": "error", "error": f"No chart files found in {_DATA_DIR}", "results": []}

    _log.info("Batch replay: discovered %d chart file(s)", len(pairs))

    # Normalise any stale bare-TF prediction IDs left by pre-normalisation runs.
    cleanup_tracker = PredictionTracker(tracker_path)
    cleaned = _cleanup_bare_ids(cleanup_tracker)
    if cleaned:
        _log.info("Batch replay: cleaned %d stale bare-TF IDs from tracker", cleaned)

    results: list[dict[str, Any]] = []
    total_predictions = 0
    total_correct = 0
    errors_encountered: list[str] = []

    for symbol, timeframe in pairs:
        _log.info("Batch: replaying %s / %s", symbol, timeframe)
        try:
            r = run_replay(
                symbol=symbol,
                timeframe=timeframe,
                window=window,
                horizon=horizon,
                min_move=min_move,
                dry_run=dry_run,
                tracker_path=tracker_path,
            )
            results.append(r)
            total_predictions += r.get("predictions_evaluated", 0)
            total_correct += r.get("correct", 0)
            if r.get("status") != "ok":
                errors_encountered.append(f"{symbol}/{timeframe}: {r.get('errors', [])}")
        except Exception as exc:
            _log.warning("Batch error for %s/%s: %s", symbol, timeframe, exc)
            errors_encountered.append(f"{symbol}/{timeframe}: {exc}")
            results.append({"status": "error", "symbol": symbol, "timeframe": timeframe, "error": str(exc)})

    batch_accuracy = round(total_correct / total_predictions * 100, 2) if total_predictions else 0.0
    # Return final learned weights from last successful run
    final_weights = next(
        (r.get("learned_weights", {}) for r in reversed(results) if r.get("learned_weights")),
        {},
    )

    summary = {
        "status": "ok" if not errors_encountered else "partial",
        "dry_run": dry_run,
        "files_processed": len(pairs),
        "total_predictions": total_predictions,
        "total_correct": total_correct,
        "batch_accuracy_pct": batch_accuracy,
        "final_learned_weights": final_weights,
        "batch_errors": errors_encountered,
        "cleaned_bare_ids": cleaned,
        "results": results,
    }
    _log.info(
        "Batch complete: %d files | %d predictions | %d correct | %.1f%% accuracy",
        len(pairs), total_predictions, total_correct, batch_accuracy,
    )
    return summary


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AstroQuant backtest replay loop")
    p.add_argument("--symbol",    default="GC.FUT",  help="Symbol prefix (default: GC.FUT)")
    p.add_argument("--timeframe", default="5m",       help="Timeframe suffix (default: 5m)")
    p.add_argument("--window",    type=int, default=12, help="Lookback bars for signal (default: 12)")
    p.add_argument("--horizon",   type=int, default=24, help="Forward bars for outcome (default: 24)")
    p.add_argument("--min-move",  type=float, default=3.0, dest="min_move",
                   help="Min price move (pips) to call directional outcome (default: 3.0)")
    p.add_argument("--dry-run",   action="store_true", help="Print results without saving to tracker")
    p.add_argument("--tracker",   default=None, help="Path to prediction_tracker.json (uses default if omitted)")
    p.add_argument("--batch",     action="store_true",
                   help="Auto-discover and replay ALL last_known_chart_*.json files")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.batch:
        result = run_batch_replay(
            window=args.window,
            horizon=args.horizon,
            min_move=args.min_move,
            dry_run=args.dry_run,
            tracker_path=args.tracker,
        )
    else:
        result = run_replay(
            symbol       = args.symbol,
            timeframe    = args.timeframe,
            window       = args.window,
            horizon      = args.horizon,
            min_move     = args.min_move,
            dry_run      = args.dry_run,
            tracker_path = args.tracker,
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
