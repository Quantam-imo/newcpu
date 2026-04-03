from __future__ import annotations

import concurrent.futures
import importlib.util
import inspect
import logging
import multiprocessing as mp
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query


router = APIRouter(prefix="/market_causality", tags=["market-causality"])

_module_lock = threading.Lock()
_module = None
_cache_lock = threading.Lock()
_cache_payloads: dict[str, dict[str, Any]] = {}
_cache_ts_by_key: dict[str, float] = {}
_CACHE_TTL_SECONDS = 30.0
_SUMMARY_TIMEOUT_SECONDS = max(5.0, float(os.getenv("MCL_SUMMARY_TIMEOUT_SECONDS", "40")))
_MATRIX_TIMEFRAMES = ("1d", "4h", "1h", "30m", "15m", "5m", "1m", "1w", "1month")
_MATRIX_MAX_WORKERS = max(1, int(os.getenv("MCL_MATRIX_MAX_WORKERS", "4")))


def _timeframe_seconds(timeframe: str | None) -> int:
    tf = str(timeframe or "1d").strip().lower()
    return {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "4h": 14400,
        "1d": 86400,
        "1w": 604800,
        "1month": 2592000,
    }.get(tf, 86400)


def _driver_score_map(drivers: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if not isinstance(drivers, list):
        return out
    for item in drivers:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        pct = item.get("score_pct")
        try:
            out[label] = float(pct)
        except (TypeError, ValueError):
            out[label] = 0.0
    return out


def _build_reasoning_delta(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if not previous:
        return {
            "has_previous": False,
            "previous_signal": None,
            "signal_changed": False,
            "top_driver_deltas": [],
        }

    current_signal = str(current.get("signal") or "")
    previous_signal = str(previous.get("signal") or "")

    curr_map = _driver_score_map(current.get("reasoning_top_drivers"))
    prev_map = _driver_score_map(previous.get("reasoning_top_drivers"))

    labels = sorted(set(curr_map.keys()) | set(prev_map.keys()))
    deltas = []
    for label in labels:
        curr = float(curr_map.get(label, 0.0))
        prev = float(prev_map.get(label, 0.0))
        delta = round(curr - prev, 2)
        deltas.append(
            {
                "label": label,
                "current_pct": round(curr, 2),
                "previous_pct": round(prev, 2),
                "delta_pct": delta,
            }
        )

    deltas = sorted(deltas, key=lambda item: abs(float(item.get("delta_pct", 0.0))), reverse=True)
    return {
        "has_previous": True,
        "previous_signal": previous_signal or None,
        "signal_changed": bool(current_signal and previous_signal and current_signal != previous_signal),
        "top_driver_deltas": deltas,
    }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _module_path() -> Path:
    return _repo_root() / "market-causality-lab" / "main.py"


def _load_module() -> Any:
    global _module

    if _module is not None:
        return _module

    with _module_lock:
        if _module is not None:
            return _module

        module_path = _module_path()
        if not module_path.exists():
            raise FileNotFoundError(f"market-causality-lab module not found: {module_path}")

        module_root = str(module_path.parent)
        if module_root not in sys.path:
            # Ensure market-causality-lab absolute imports like `from backend...` resolve.
            sys.path.insert(0, module_root)

        spec = importlib.util.spec_from_file_location("market_causality_lab_main", str(module_path))
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to create module spec for market-causality-lab")

        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        _module = loaded
        return _module


def _normalize_symbol(symbol: str | None) -> str:
    value = str(symbol or "").strip().upper()
    return value or "XAUUSD"


def _normalize_timeframe(timeframe: str | None) -> str:
    value = str(timeframe or "").strip().lower()
    return value or "1m"


def _normalize_source_mode(source_mode: str | None) -> str:
    value = str(source_mode or "historical_first").strip().lower()
    allowed = {"historical_first", "historical_only", "live_first", "live_only", "hybrid"}
    return value if value in allowed else "historical_first"


def _normalize_lookback_years(lookback_years: int | None) -> int:
    years = int(lookback_years) if lookback_years is not None else 25
    return max(1, min(100, years))


def _cache_key(symbol: str, timeframe: str, lookback_years: int, source_mode: str) -> str:
    return f"{symbol}|{timeframe}|{lookback_years}|{source_mode}"


def _run_full_system(
    module: Any,
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    full_system = getattr(module, "full_system", None)
    if not callable(full_system):
        raise RuntimeError("market-causality-lab full_system() is unavailable")

    signature = inspect.signature(full_system)
    accepts_symbol = "symbol" in signature.parameters
    accepts_timeframe = "timeframe" in signature.parameters
    accepts_lookback_years = "lookback_years" in signature.parameters
    accepts_source_mode = "source_mode" in signature.parameters

    call_kwargs: dict[str, Any] = {}
    if accepts_symbol:
        call_kwargs["symbol"] = symbol
    if accepts_timeframe:
        call_kwargs["timeframe"] = timeframe
    if accepts_lookback_years:
        call_kwargs["lookback_years"] = lookback_years
    if accepts_source_mode:
        call_kwargs["source_mode"] = source_mode

    payload = full_system(**call_kwargs)

    applied_symbol = str(payload.get("symbol") or (symbol if accepts_symbol else "XAUUSD")).strip().upper()
    applied_timeframe = str(
        payload.get("applied_timeframe")
        or payload.get("timeframe")
        or (timeframe if accepts_timeframe else "1m")
    ).strip().lower()
    requested_timeframe = str(payload.get("requested_timeframe") or timeframe).strip().lower()
    alignment = {
        "requested_symbol": symbol,
        "requested_timeframe": requested_timeframe,
        "applied_symbol": applied_symbol,
        "applied_timeframe": applied_timeframe,
        "native_symbol_support": accepts_symbol,
        "native_timeframe_support": accepts_timeframe,
        "requested_lookback_years": lookback_years,
        "requested_source_mode": source_mode,
        "native_lookback_support": accepts_lookback_years,
        "native_source_mode_support": accepts_source_mode,
        "timeframe_fallback_applied": bool(payload.get("timeframe_fallback_applied")),
        "timeframe_fallback_reason": payload.get("timeframe_fallback_reason"),
    }
    return payload, alignment


def _run_full_system_worker(
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
    out_queue: mp.Queue,
) -> None:
    """Run full_system in an isolated process so parent can enforce timeout safely."""
    try:
        module = _load_module()
        previous_cwd = os.getcwd()
        try:
            os.chdir(str(_module_path().parent))
            payload, alignment = _run_full_system(
                module,
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                source_mode=source_mode,
            )
        finally:
            os.chdir(previous_cwd)
        out_queue.put({"ok": True, "payload": payload, "alignment": alignment})
    except Exception as exc:
        out_queue.put({"ok": False, "error": str(exc)})


def _run_full_system_with_timeout(
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    queue: mp.Queue = mp.Queue(maxsize=1)
    proc = mp.Process(
        target=_run_full_system_worker,
        args=(symbol, timeframe, lookback_years, source_mode, queue),
        daemon=True,
    )
    proc.start()
    proc.join(timeout=max(1.0, float(timeout_seconds)))

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=1.0)
        raise TimeoutError(f"market-causality summary timed out after {timeout_seconds:.1f}s")

    if queue.empty():
        raise RuntimeError("market-causality summary process returned no payload")

    message = queue.get()
    if not bool(message.get("ok")):
        raise RuntimeError(str(message.get("error") or "unknown full_system worker error"))

    return dict(message.get("payload") or {}), dict(message.get("alignment") or {})


def _run_full_system_in_process(
    symbol: str,
    timeframe: str,
    lookback_years: int,
    source_mode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    module = _load_module()
    previous_cwd = os.getcwd()
    try:
        os.chdir(str(_module_path().parent))
        payload, alignment = _run_full_system(
            module,
            symbol=symbol,
            timeframe=timeframe,
            lookback_years=lookback_years,
            source_mode=source_mode,
        )
    finally:
        os.chdir(previous_cwd)
    return payload, alignment


_ORIGINAL_LOAD_MODULE = _load_module
_ORIGINAL_RUN_FULL_SYSTEM = _run_full_system


def _compute_summary(
    refresh: bool = False,
    symbol: str = "XAUUSD",
    timeframe: str = "1d",
    lookback_years: int = 25,
    source_mode: str = "historical_first",
) -> dict[str, Any]:
    symbol = _normalize_symbol(symbol)
    timeframe = _normalize_timeframe(timeframe)
    lookback_years = _normalize_lookback_years(lookback_years)
    source_mode = _normalize_source_mode(source_mode)
    key = _cache_key(symbol, timeframe, lookback_years, source_mode)

    now = time.time()
    if not refresh:
        with _cache_lock:
            cached = _cache_payloads.get(key)
            cached_ts = _cache_ts_by_key.get(key)
            if cached is not None and cached_ts is not None and (now - cached_ts) <= _CACHE_TTL_SECONDS:
                return cached

    started_at = time.time()
    with _cache_lock:
        previous_for_key = _cache_payloads.get(key)

    try:
        use_timeout_isolation = (
            _load_module is _ORIGINAL_LOAD_MODULE
            and _run_full_system is _ORIGINAL_RUN_FULL_SYSTEM
        )
        if use_timeout_isolation:
            payload, alignment = _run_full_system_with_timeout(
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                source_mode=source_mode,
                timeout_seconds=_SUMMARY_TIMEOUT_SECONDS,
            )
        else:
            payload, alignment = _run_full_system_in_process(
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                source_mode=source_mode,
            )

        summary = {
            "status": "ok",
            "source": payload.get("data_source"),
            "symbol": payload.get("symbol"),
            "requested_timeframe": payload.get("requested_timeframe") or alignment.get("requested_timeframe"),
            "applied_timeframe": payload.get("applied_timeframe") or alignment.get("applied_timeframe"),
            "timeframe_fallback_applied": bool(
                payload.get("timeframe_fallback_applied")
                or alignment.get("timeframe_fallback_applied")
            ),
            "timeframe_fallback_reason": payload.get("timeframe_fallback_reason") or alignment.get("timeframe_fallback_reason"),
            "signal": payload.get("filtered_signal"),
            "confidence": payload.get("confidence"),
            "quality": payload.get("quality"),
            "phase": (payload.get("final") or {}).get("phase"),
            "trend": (payload.get("final") or {}).get("trend"),
            "trap": (payload.get("trap") or {}).get("trap"),
            "reliability_score": (payload.get("decision_trace") or {}).get("reliability_score"),
            "bias_score": (payload.get("simple") or {}).get("bias_score"),
            "bias_label": (payload.get("simple") or {}).get("bias_label"),
            "news_guard_applied": bool(payload.get("news_guard_applied")),
            "rejection_reason": payload.get("rejection_reason") or "none",
            "trade_levels": payload.get("trade_levels"),
            "institutional_decision": (payload.get("institutional") or {}).get("institutional_decision"),
            "institutional_score": (payload.get("institutional") or {}).get("institutional_score"),
            "contracts": payload.get("output_contracts"),
            "instrument_alignment": alignment,
            "lookback_years": payload.get("lookback_years", lookback_years),
            "source_mode": payload.get("source_mode", source_mode),
            "rows_analyzed": payload.get("rows_analyzed"),
            "historical_depth_years": payload.get("historical_depth_years"),
            "applied_dataset_depth_years": payload.get("applied_dataset_depth_years"),
            "lookback_target_met": payload.get("lookback_target_met"),
            "lookback_depth_warning": payload.get("lookback_depth_warning"),
            "news_status": payload.get("news_status"),
            "global_events_status": payload.get("global_events_status"),
            "observation_id": payload.get("observation_id"),
            "observation_log_path": payload.get("observation_log_path"),
            "observation_error": payload.get("observation_error"),
            "observation": payload.get("observation"),
            "observation_trend_start_time": ((payload.get("observation") or {}).get("trend_start_time")),
            "observation_latest_time": ((payload.get("observation") or {}).get("latest_time")),
            "observation_news_previous_time": ((payload.get("observation") or {}).get("news_previous_time")),
            "observation_news_next_time": ((payload.get("observation") or {}).get("news_next_time")),
            "observation_gann_degree": ((payload.get("observation") or {}).get("gann_degree")),
            "observation_geometry_angle_deg": ((payload.get("observation") or {}).get("geometry_angle_deg")),
            "observation_physics_velocity": ((payload.get("observation") or {}).get("physics_velocity_price_per_hour")),
            "observation_price_time_ratio": ((payload.get("observation") or {}).get("price_time_ratio")),
            "observation_degree_time_ratio": ((payload.get("observation") or {}).get("degree_time_ratio")),
            "analysis_started_at_utc": payload.get("analysis_started_at_utc"),
            "analysis_completed_at_utc": payload.get("analysis_completed_at_utc"),
            "analysis_elapsed_ms": payload.get("analysis_elapsed_ms"),
            "analysis_lifecycle": payload.get("analysis_lifecycle"),
            "memory_size": payload.get("memory_size"),
            "ai_decision": payload.get("ai_decision"),
            "reasoning_display": payload.get("reasoning_display"),
            "reasoning_tone": ((payload.get("reasoning_display") or {}).get("tone")),
            "reasoning_summary": ((payload.get("reasoning_display") or {}).get("summary")),
            "reasoning_chain": ((payload.get("reasoning_display") or {}).get("chain")),
            "reasoning_top_drivers": ((payload.get("reasoning_display") or {}).get("top_drivers")),
            "ai_model": payload.get("ai_model"),
            "ai_model_used": bool(((payload.get("ai_model") or {}).get("used_model"))),
            "ai_model_version": ((payload.get("ai_model") or {}).get("version")),
            "process_timing": payload.get("process_timing"),
            "slowest_process_stage": max(
                payload.get("process_timing") or [],
                key=lambda item: float(item.get("elapsed_ms", 0.0) or 0.0),
                default=None,
            ),
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
            "updated_at": int(time.time()),
        }
        summary["reasoning_delta"] = _build_reasoning_delta(summary, previous_for_key)
    except TimeoutError as exc:
        logging.warning("market-causality summary timeout: %s", exc)
        if previous_for_key:
            summary = dict(previous_for_key)
            summary["status"] = "stale_timeout"
            summary["error"] = str(exc)
            summary["cache_fallback_used"] = True
            summary["elapsed_ms"] = round((time.time() - started_at) * 1000.0, 2)
            summary["updated_at"] = int(time.time())
        else:
            summary = {
                "status": "timeout",
                "error": str(exc),
                "cache_fallback_used": False,
                "symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "timeframe_fallback_applied": False,
                "timeframe_fallback_reason": None,
                "instrument_alignment": {
                    "requested_symbol": symbol,
                    "requested_timeframe": timeframe,
                    "applied_timeframe": timeframe,
                    "requested_lookback_years": lookback_years,
                    "requested_source_mode": source_mode,
                    "timeframe_fallback_applied": False,
                    "timeframe_fallback_reason": None,
                },
                "lookback_years": lookback_years,
                "source_mode": source_mode,
                "rows_analyzed": None,
                "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
                "updated_at": int(time.time()),
            }
    except Exception as exc:  # pragma: no cover - defensive runtime bridge
        logging.exception("market-causality summary failed")
        summary = {
            "status": "error",
            "error": str(exc),
            "symbol": symbol,
            "requested_timeframe": timeframe,
            "applied_timeframe": timeframe,
            "timeframe_fallback_applied": False,
            "timeframe_fallback_reason": None,
            "instrument_alignment": {
                "requested_symbol": symbol,
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "requested_lookback_years": lookback_years,
                "requested_source_mode": source_mode,
                "timeframe_fallback_applied": False,
                "timeframe_fallback_reason": None,
            },
            "lookback_years": lookback_years,
            "source_mode": source_mode,
            "rows_analyzed": None,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
            "updated_at": int(time.time()),
        }

    with _cache_lock:
        _cache_payloads[key] = summary
        _cache_ts_by_key[key] = time.time()

    return summary


def _compute_timeframe_matrix(
    refresh: bool = False,
    symbol: str = "XAUUSD",
    lookback_years: int = 25,
    source_mode: str = "historical_first",
) -> dict[str, Any]:
    started_at = time.time()
    symbol = _normalize_symbol(symbol)
    lookback_years = _normalize_lookback_years(lookback_years)
    source_mode = _normalize_source_mode(source_mode)

    rows: list[dict[str, Any]] = []
    ok_count = 0

    def _summary_to_row(tf: str, summary: dict[str, Any]) -> dict[str, Any]:
        process_timing = summary.get("process_timing") or []
        return {
            "timeframe": tf,
            "status": summary.get("status"),
            "signal": summary.get("signal"),
            "confidence": summary.get("confidence"),
            "quality": summary.get("quality"),
            "requested_timeframe": summary.get("requested_timeframe"),
            "applied_timeframe": summary.get("applied_timeframe"),
            "timeframe_fallback_applied": summary.get("timeframe_fallback_applied"),
            "timeframe_fallback_reason": summary.get("timeframe_fallback_reason"),
            "rows_analyzed": summary.get("rows_analyzed"),
            "historical_depth_years": summary.get("historical_depth_years"),
            "lookback_target_met": summary.get("lookback_target_met"),
            "lookback_depth_warning": summary.get("lookback_depth_warning"),
            "memory_size": summary.get("memory_size"),
            "engine_stage_count": len(process_timing) if isinstance(process_timing, list) else 0,
            "engine_stage_names": [
                str(item.get("name")) for item in process_timing if isinstance(item, dict) and item.get("name")
            ] if isinstance(process_timing, list) else [],
            "ai_model_used": summary.get("ai_model_used"),
            "ai_model_version": summary.get("ai_model_version"),
            "ai_decision": summary.get("ai_decision"),
            "reasoning_summary": summary.get("reasoning_summary"),
            "reasoning_top_drivers": summary.get("reasoning_top_drivers"),
            "observation": summary.get("observation"),
            "observation_trend_start_time": summary.get("observation_trend_start_time"),
            "observation_latest_time": summary.get("observation_latest_time"),
            "observation_news_previous_time": summary.get("observation_news_previous_time"),
            "observation_news_next_time": summary.get("observation_news_next_time"),
            "observation_gann_degree": summary.get("observation_gann_degree"),
            "observation_price_time_ratio": summary.get("observation_price_time_ratio"),
            "observation_degree_time_ratio": summary.get("observation_degree_time_ratio"),
            "news_status": summary.get("news_status"),
            "global_events_status": summary.get("global_events_status"),
            "elapsed_ms": summary.get("elapsed_ms"),
            "error": summary.get("error"),
        }

    by_tf: dict[str, dict[str, Any]] = {}
    worker_count = max(1, min(len(_MATRIX_TIMEFRAMES), _MATRIX_MAX_WORKERS))

    with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
        future_map = {
            executor.submit(
                _compute_summary,
                refresh,
                symbol,
                tf,
                lookback_years,
                source_mode,
            ): tf
            for tf in _MATRIX_TIMEFRAMES
        }

        for future in concurrent.futures.as_completed(future_map):
            tf = future_map[future]
            try:
                summary = future.result()
                status = str(summary.get("status") or "").lower()
                if status in {"ok", "stale_timeout"}:
                    ok_count += 1
                by_tf[tf] = _summary_to_row(tf, summary)
            except Exception as exc:
                by_tf[tf] = {
                    "timeframe": tf,
                    "status": "error",
                    "error": str(exc),
                }

    # Preserve canonical timeframe order for stable UI rendering.
    rows = [by_tf.get(tf, {"timeframe": tf, "status": "error", "error": "missing_row"}) for tf in _MATRIX_TIMEFRAMES]

    coverage_pct = round((ok_count / max(1, len(_MATRIX_TIMEFRAMES))) * 100.0, 2)
    return {
        "status": "ok",
        "symbol": symbol,
        "lookback_years": lookback_years,
        "source_mode": source_mode,
        "timeframes": list(_MATRIX_TIMEFRAMES),
        "rows": rows,
        "coverage": {
            "ok_count": ok_count,
            "total": len(_MATRIX_TIMEFRAMES),
            "ok_pct": coverage_pct,
        },
        "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        "updated_at": int(time.time()),
    }


def _compute_chart(
    symbol: str = "XAUUSD",
    timeframe: str = "1d",
    lookback_years: int = 25,
    limit: int = 12000,
) -> dict[str, Any]:
    symbol = _normalize_symbol(symbol)
    timeframe = _normalize_timeframe(timeframe)
    lookback_years = _normalize_lookback_years(lookback_years)
    limit = max(100, min(int(limit), 50000))

    started_at = time.time()
    try:
        module = _load_module()
        data_dir = str(_repo_root() / "market-causality-lab" / "data")

        load_with_fallback = getattr(module, "_load_historical_with_fallback", None)
        if callable(load_with_fallback):
            df, _dataset_path, applied_timeframe, fallback_meta = load_with_fallback(
                symbol=symbol,
                timeframe=timeframe,
                lookback_years=lookback_years,
                data_dir=data_dir,
            )
        else:
            resolve_timeframe_file = getattr(module, "_resolve_timeframe_file", None)
            load_data = getattr(module, "load_data", None)
            apply_lookback = getattr(module, "_apply_lookback_years", None)
            if not callable(resolve_timeframe_file) or not callable(load_data) or not callable(apply_lookback):
                raise RuntimeError("market-causality-lab historical chart helpers are unavailable")

            path = resolve_timeframe_file(timeframe=timeframe, symbol=symbol, data_dir=data_dir)
            raw_df = load_data(str(path))
            df = apply_lookback(raw_df, lookback_years)
            applied_timeframe = timeframe
            fallback_meta = {
                "requested_timeframe": timeframe,
                "applied_timeframe": timeframe,
                "fallback_applied": False,
                "fallback_reason": None,
            }

        if "time" not in df.columns:
            raise RuntimeError("historical dataset is missing required time column")

        rows = []
        subset = df[["time", "open", "high", "low", "close", "volume"]].copy()
        subset = subset.dropna(subset=["time", "open", "high", "low", "close"])
        subset = subset.sort_values("time")
        if len(subset) > limit:
            subset = subset.tail(limit)

        historical_last_epoch = None

        for item in subset.itertuples(index=False):
            ts = getattr(item, "time", None)
            try:
                epoch = int(ts.timestamp())
                o = float(getattr(item, "open"))
                h = float(getattr(item, "high"))
                l = float(getattr(item, "low"))
                c = float(getattr(item, "close"))
                v = float(getattr(item, "volume", 0.0) or 0.0)
            except Exception:
                continue
            rows.append(
                {
                    "time": epoch,
                    "open": o,
                    "high": h,
                    "low": l,
                    "close": c,
                    "volume": max(0.0, v),
                }
            )
            historical_last_epoch = epoch

        live_gap_fill_applied = False
        live_gap_seconds = None
        live_last_epoch = None
        live_gap_reason = None
        try:
            fetch_live = getattr(module, "fetch_xauusd", None)
            if callable(fetch_live) and historical_last_epoch is not None:
                live_df = fetch_live(count=3)
                if "time" in live_df.columns and not live_df.empty:
                    live_df = live_df.sort_values("time")
                    live_row = live_df.iloc[-1]
                    live_time = getattr(live_row, "time", None)
                    if live_time is not None:
                        live_last_epoch = int(live_time.timestamp())
                        gap_seconds = int(max(0, live_last_epoch - historical_last_epoch))
                        live_gap_seconds = gap_seconds
                        tf_seconds = _timeframe_seconds(applied_timeframe)
                        if gap_seconds >= max(60, tf_seconds // 2):
                            o = float(getattr(live_row, "open", getattr(live_row, "close", 0.0)) or 0.0)
                            h = float(getattr(live_row, "high", getattr(live_row, "close", 0.0)) or 0.0)
                            l = float(getattr(live_row, "low", getattr(live_row, "close", 0.0)) or 0.0)
                            c = float(getattr(live_row, "close", 0.0) or 0.0)
                            v = float(getattr(live_row, "volume", 0.0) or 0.0)
                            if c > 0.0:
                                rows.append(
                                    {
                                        "time": live_last_epoch,
                                        "open": o,
                                        "high": h,
                                        "low": l,
                                        "close": c,
                                        "volume": max(0.0, v),
                                    }
                                )
                                live_gap_fill_applied = True
                                live_gap_reason = "historical_series_stale_live_tail_merged"
        except Exception as exc:
            live_gap_reason = f"live_gap_fill_unavailable: {exc}"

        if rows:
            rows = sorted(rows, key=lambda item: int(item.get("time", 0)))
            deduped = []
            last_t = None
            for item in rows:
                t = int(item.get("time", 0))
                if t == last_t:
                    deduped[-1] = item
                else:
                    deduped.append(item)
                    last_t = t
            rows = deduped

        historical_depth_fn = getattr(module, "_historical_depth_years", None)
        depth_years = float(historical_depth_fn(df)) if callable(historical_depth_fn) and not df.empty else None

        return {
            "status": "ok",
            "symbol": symbol,
            "requested_timeframe": timeframe,
            "applied_timeframe": str(applied_timeframe),
            "lookback_years": lookback_years,
            "historical_depth_years": depth_years,
            "rows": len(rows),
            "candles": rows,
            "timeframe_fallback_applied": bool(fallback_meta.get("fallback_applied")),
            "timeframe_fallback_reason": fallback_meta.get("fallback_reason"),
            "live_gap_fill_applied": live_gap_fill_applied,
            "live_gap_reason": live_gap_reason,
            "historical_last_time": historical_last_epoch,
            "live_last_time": live_last_epoch,
            "live_gap_seconds": live_gap_seconds,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "symbol": symbol,
            "requested_timeframe": timeframe,
            "lookback_years": lookback_years,
            "candles": [],
            "rows": 0,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }


@router.get("/summary")
def market_causality_summary(
    refresh: bool = Query(default=False),
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    source_mode: str = Query(default="historical_first"),
) -> dict[str, Any]:
    """Unified bridge endpoint for market-causality-lab summary data."""
    return _compute_summary(
        refresh=bool(refresh),
        symbol=symbol,
        timeframe=timeframe,
        lookback_years=lookback_years,
        source_mode=source_mode,
    )


@router.get("/status")
def market_causality_status() -> dict[str, Any]:
    module_exists = _module_path().exists()
    with _cache_lock:
        cache_keys = sorted(list(_cache_payloads.keys()))

    return {
        "module_path": str(_module_path()),
        "module_exists": module_exists,
        "module_loaded": _module is not None,
        "cache_ttl_seconds": _CACHE_TTL_SECONDS,
        "summary_timeout_seconds": _SUMMARY_TIMEOUT_SECONDS,
        "cache_entries": len(cache_keys),
        "cache_keys": cache_keys,
    }


@router.get("/chart")
def market_causality_chart(
    symbol: str = Query(default="XAUUSD"),
    timeframe: str = Query(default="1d"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    limit: int = Query(default=12000, ge=100, le=50000),
) -> dict[str, Any]:
    """Historical candlestick data for the MCL dashboard chart."""
    return _compute_chart(
        symbol=symbol,
        timeframe=timeframe,
        lookback_years=lookback_years,
        limit=limit,
    )


@router.get("/live_price")
def market_causality_live_price(
    symbol: str = Query(default="XAUUSD"),
) -> dict[str, Any]:
    """Return the most recent XAUUSD/GC live price.

    Attempts MT5 (via MCL module fetch_xauusd) first, then falls back to
    Databento Historical API using the last 1-minute bar from GLBX.MDP3.
    Used by the MCL dashboard for periodic live price polling.
    """
    import pandas as _pd

    symbol = _normalize_symbol(symbol)
    started_at = time.time()

    # --- attempt 1: MCL module fetch_xauusd (MT5-backed or Databento fallback) ---
    try:
        module = _load_module()
        fetch_live = getattr(module, "fetch_xauusd", None)
        if callable(fetch_live):
            df = fetch_live(count=3)
            if not df.empty:
                last = df.iloc[-1]
                close_price = float(getattr(last, "close", None) or 0.0)
                raw_ts = getattr(last, "time", None)
                ts = int(_pd.Timestamp(raw_ts).timestamp()) if raw_ts is not None else None
                if close_price > 0.0:
                    return {
                        "status": "ok",
                        "symbol": symbol,
                        "price": round(close_price, 4),
                        "source": "mt5_or_databento",
                        "ts": ts,
                        "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
                    }
    except Exception:
        pass  # fall through to direct Databento attempt

    # --- attempt 2: direct Databento Historical API ---
    try:
        api_key = str(os.getenv("DATABENTO_API_KEY", "")).strip()
        if not api_key:
            raise RuntimeError("DATABENTO_API_KEY is not configured")
        import databento as _db  # type: ignore[import]

        client = _db.Historical(api_key)
        data = client.timeseries.get_range(
            dataset="GLBX.MDP3",
            symbols=["GC.c.0"],
            stype_in="continuous",
            schema="ohlcv-1m",
            start="now-15m",
        )
        df = data.to_df()
        if df.empty:
            raise RuntimeError("Empty Databento OHLCV response")

        if df.index.name in ("ts_event", "ts_recv") or hasattr(df.index, "tz"):
            df = df.reset_index()

        close_col = "close" if "close" in df.columns else df.columns[-1]
        ts_col = next(
            (c for c in ("ts_event", "ts_recv", "time") if c in df.columns), None
        )
        last_row = df.iloc[-1]
        price = float(last_row[close_col])
        raw_ts = last_row[ts_col] if ts_col else None
        ts = int(_pd.Timestamp(raw_ts).timestamp()) if raw_ts is not None else None

        return {
            "status": "ok",
            "symbol": symbol,
            "price": round(price, 4),
            "source": "databento",
            "ts": ts,
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "symbol": symbol,
            "price": None,
            "source": None,
            "error": str(exc),
            "elapsed_ms": round((time.time() - started_at) * 1000.0, 2),
        }


@router.get("/timeframe_matrix")
def market_causality_timeframe_matrix(
    refresh: bool = Query(default=False),
    symbol: str = Query(default="XAUUSD"),
    lookback_years: int = Query(default=25, ge=1, le=100),
    source_mode: str = Query(default="historical_first"),
) -> dict[str, Any]:
    """Aggregated timeframe-wise AI observation matrix payload."""
    return _compute_timeframe_matrix(
        refresh=bool(refresh),
        symbol=symbol,
        lookback_years=lookback_years,
        source_mode=source_mode,
    )
