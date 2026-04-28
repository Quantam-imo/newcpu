from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backend.ai.modeling.baseline_models import available_model_factories
from backend.ai.modeling.calibration import (
    accuracy_from_prob,
    apply_temperature,
    brier_score,
    fit_temperature,
    log_loss,
)
from backend.ai.modeling.feature_pipeline import (
    DEFAULT_LABEL_MODE,
    DEFAULT_SETUP_MODE,
    DEFAULT_STOP_RETURN_PCT,
    DEFAULT_TARGET_RETURN_PCT,
    FEATURE_NAMES,
    LAYERED_FEATURE_NAMES,
    build_dataset_from_memory,
    feature_names_for_version,
    label_config,
    setup_config,
    standardize_fit,
    standardize_transform,
)
from backend.ai.modeling.walkforward import walkforward_validate
from backend.memory.scanner import scan_market
from backend.utils.data_loader import integrate_news_features, load_data
from backend.utils.master_cycle_features import add_master_cycle_state_features
from backend.utils.timeframe_loader import TIMEFRAME_FILES
from train_ai_models import (
    _apply_lookback_years,
    _load_and_merge_events,
    _load_direct_table_events,
    _load_master_cycle_events,
)


FEATURE_GROUPS = {
    "market_core": [
        "base_trend",
        "base_momentum",
        "base_volatility",
        "physics_force",
        "physics_velocity",
        "state_price",
    ],
    "gann": [
        "gann_zone_reversal",
        "cycle_gann_degree",
    ],
    "liquidity_ict": [
        "liq_buy_side_sweep",
        "liq_sell_side_sweep",
        "structure_bos_up",
        "structure_bos_down",
        "structure_choch_up",
        "structure_choch_down",
        "structure_hh_hl",
        "structure_ll_lh",
        "structure_trend_strength",
        "trap_buyer",
        "trap_seller",
        "trap_probability",
    ],
    "news": [
        "news_impact_score",
        "news_event_count",
        "news_high_impact_active",
    ],
    "signals_confluence": [
        "signal_buy_flag",
        "signal_sell_flag",
        "reliability_score",
        "conflict_score",
        "confluence_ready",
        "buy_force",
        "sell_force",
    ],
    "compression": [
        "compression_score",
        "compression_breakout_near",
        "compression_silence_active",
        "compression_cycle_tightening",
        "compression_energy_stored",
        "compression_bars_in_compression",
    ],
    "astro_cycle": [
        "cycle_moon_phase_position",
        "cycle_nakshatra_sequence",
        "cycle_days_to_next_node",
        "cycle_planetary_active",
    ],
    "regime_phase": [
        "phase_code",
        "regime_trend_up",
        "regime_trend_down",
        "regime_range",
        "regime_transition",
        "phase_accumulation",
        "phase_manipulation",
        "phase_expansion",
        "phase_distribution",
        "phase_neutral",
        "signal_active_in_accumulation",
        "signal_active_in_manipulation",
        "signal_active_in_distribution",
    ],
}

LAYERED_GROUPS = {
    "time_planetary": [
        "time_planetary_aspects_active",
        "time_planetary_conjunction_active",
        "time_planetary_square_active",
        "time_planetary_opposition_active",
        "time_retrograde_active",
    ],
    "time_lunar": [
        "time_moon_phase_active",
        "time_nakshatra_transition_active",
        "time_moon_eclipse_active",
        "time_moon_new_active",
        "time_moon_full_active",
    ],
    "time_gann": [
        "time_sq9_level_active",
        "time_gann_45_cycle_active",
        "time_gann_90_cycle_active",
        "time_gann_180_cycle_active",
        "time_gann_pressure_window",
        "time_gann_station_active",
        "time_gann_synodic_active",
        "time_gann_time_cycle_exact",
    ],
    "time_context": [
        "time_cycle_active",
        "time_window_score",
    ],
    "location": [
        "location_bullish_fvg_near",
        "location_bearish_fvg_near",
        "location_bullish_order_block_near",
        "location_bearish_order_block_near",
        "location_equal_highs_near",
        "location_equal_lows_near",
        "location_session_high_near",
        "location_session_low_near",
        "location_at_key_level",
        "location_zone_score",
    ],
    "trigger": [
        "trigger_sweep_buy_side",
        "trigger_sweep_sell_side",
        "trigger_mss_bullish",
        "trigger_mss_bearish",
        "trigger_bos_bullish",
        "trigger_bos_bearish",
        "trigger_displacement_bullish",
        "trigger_displacement_bearish",
        "trigger_confirmed",
    ],
    "participation": [
        "participation_news_active",
        "participation_volume_spike",
        "participation_london_open",
        "participation_newyork_open",
        "participation_score",
        "participation_strong",
    ],
    "decision": [
        "decision_time_score",
        "decision_execute_trade",
    ],
}


GROUP_ALIASES = {
    "time_engine": [
        "time_planetary",
        "time_lunar",
        "time_gann",
        "time_context",
    ]
}


def _time_split(X: np.ndarray, y: np.ndarray, train_ratio: float = 0.8):
    n = len(X)
    cut = max(20, min(n - 5, int(n * train_ratio)))
    return X[:cut], y[:cut], X[cut:], y[cut:]


def _timeframe_path(data_dir: str, timeframe: str) -> Path:
    tf = str(timeframe or "1d").strip().lower()
    filename = TIMEFRAME_FILES.get(tf)
    if not filename:
        supported = ", ".join(sorted(TIMEFRAME_FILES.keys()))
        raise ValueError(f"Unsupported timeframe '{timeframe}'. Supported: {supported}")
    return Path(data_dir) / filename


def _validate_feature_groups() -> None:
    all_features = set(FEATURE_NAMES) | set(LAYERED_FEATURE_NAMES)
    defined = []
    all_groups = {**FEATURE_GROUPS, **LAYERED_GROUPS}
    for group, names in all_groups.items():
        unknown = sorted(set(names) - all_features)
        if unknown:
            raise ValueError(f"Feature group '{group}' references unknown features: {unknown}")
        defined.extend(names)
    duplicated = sorted({name for name in defined if defined.count(name) > 1})
    if duplicated:
        raise ValueError(f"Feature groups must be disjoint for ablation. Duplicated: {duplicated}")


def _resolve_groups(group_arg: str | None) -> list[str]:
    supported_groups = {**FEATURE_GROUPS, **LAYERED_GROUPS}
    supported_names = set(supported_groups) | set(GROUP_ALIASES)
    if not group_arg:
        return list(supported_groups.keys())
    selected = [item.strip() for item in group_arg.split(",") if item.strip()]
    unknown = [item for item in selected if item not in supported_names]
    if unknown:
        supported = ", ".join(sorted(supported_names))
        raise ValueError(f"Unknown groups: {', '.join(unknown)}. Supported: {supported}")
    resolved: list[str] = []
    for item in selected:
        for group in GROUP_ALIASES.get(item, [item]):
            if group not in resolved:
                resolved.append(group)
    return resolved


def _feature_indexes(names: list[str]) -> list[int]:
    raise RuntimeError("Use _feature_indexes_for_version")


def _feature_indexes_for_version(feature_version: str, names: list[str]) -> list[int]:
    feature_names = feature_names_for_version(feature_version)
    return [feature_names.index(name) for name in names]


def _mask_columns(X: np.ndarray, column_indexes: list[int]) -> np.ndarray:
    masked = X.copy()
    if column_indexes:
        masked[:, column_indexes] = 0.0
    return masked


def _evaluate_dataset(X: np.ndarray, y: np.ndarray) -> dict:
    if len(X) < 120:
        return {
            "trained": False,
            "reason": "insufficient_training_rows",
            "rows": int(len(X)),
        }

    X_train_raw, y_train, X_val_raw, y_val = _time_split(X, y)
    X_train, mean, std = standardize_fit(X_train_raw)
    X_val = standardize_transform(X_val_raw, mean, std)

    candidates = []
    for model_name, factory in available_model_factories():
        model = factory().fit(X_train, y_train)
        raw_p = model.predict_proba(X_val)
        temperature = fit_temperature(y_val, raw_p)
        p = apply_temperature(raw_p, temperature)
        candidates.append(
            {
                "name": model_name,
                "temperature": float(temperature),
                "brier": float(brier_score(y_val, p)),
                "accuracy": float(accuracy_from_prob(y_val, p)),
                "log_loss": float(log_loss(y_val, p)),
            }
        )

    candidates.sort(key=lambda item: (item["brier"], -item["accuracy"]))
    best = candidates[0]
    X_all = standardize_transform(X, mean, std)
    walkforward = walkforward_validate(X_all, y, windows=4, min_train=300)

    return {
        "trained": True,
        "reason": "ok",
        "selected_model": best["name"],
        "validation_metrics": {
            "brier": round(best["brier"], 6),
            "accuracy": round(best["accuracy"], 6),
            "log_loss": round(best["log_loss"], 6),
            "rows_train": int(len(X_train)),
            "rows_val": int(len(X_val)),
        },
        "walkforward": walkforward,
        "leaderboard": [
            {
                "name": item["name"],
                "brier": round(item["brier"], 6),
                "accuracy": round(item["accuracy"], 6),
                "log_loss": round(item["log_loss"], 6),
            }
            for item in candidates
        ],
    }


def _delta_metrics(baseline: dict, ablated: dict) -> dict:
    base_metrics = baseline["validation_metrics"]
    ablated_metrics = ablated["validation_metrics"]
    base_walkforward = (baseline.get("walkforward") or {}).get("summary") or {}
    ablated_walkforward = (ablated.get("walkforward") or {}).get("summary") or {}

    def _delta(current: float | None, prior: float | None) -> float | None:
        if current is None or prior is None:
            return None
        return round(float(current) - float(prior), 6)

    return {
        "delta_brier": _delta(ablated_metrics.get("brier"), base_metrics.get("brier")),
        "delta_accuracy": _delta(ablated_metrics.get("accuracy"), base_metrics.get("accuracy")),
        "delta_log_loss": _delta(ablated_metrics.get("log_loss"), base_metrics.get("log_loss")),
        "delta_walkforward_brier": _delta(
            ablated_walkforward.get("avg_brier"),
            base_walkforward.get("avg_brier"),
        ),
        "delta_walkforward_accuracy": _delta(
            ablated_walkforward.get("avg_accuracy"),
            base_walkforward.get("avg_accuracy"),
        ),
    }


def _load_memory_dataset(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, dict]:
    path = _timeframe_path(args.data_dir, args.timeframe)
    if not path.exists():
        raise FileNotFoundError(f"Missing required data file: {path}")

    news_df = _load_and_merge_events(args.news_file, *(args.astro_file or []))
    direct_df = _load_direct_table_events(args.direct_table)
    if direct_df is not None:
        if news_df is None:
            news_df = direct_df
        else:
            news_df = pd.concat([news_df, direct_df], ignore_index=True)
            news_df = news_df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    master_cycles_df = _load_master_cycle_events(args.master_cycles)
    if master_cycles_df is not None:
        if news_df is None:
            news_df = master_cycles_df
        else:
            news_df = pd.concat([news_df, master_cycles_df], ignore_index=True)
            news_df = news_df.dropna(subset=["time"]).sort_values("time").reset_index(drop=True)

    df = load_data(str(path))
    df = _apply_lookback_years(df, int(args.lookback_years))
    df = integrate_news_features(df, news_df)
    df = add_master_cycle_state_features(df, args.master_cycles)

    memory = scan_market(df)
    X, y = build_dataset_from_memory(
        memory,
        horizon=max(1, int(args.horizon)),
        label_mode=str(args.label_mode or DEFAULT_LABEL_MODE),
        target_return_pct=float(args.target_return_pct),
        stop_return_pct=float(args.stop_return_pct),
        feature_version=str(args.feature_version),
        setup_mode=str(args.setup_mode or DEFAULT_SETUP_MODE),
    )
    metadata = {
        "dataset_path": str(path),
        "rows_used": int(len(df)),
        "memory_size": int(len(memory)),
        "dataset_rows": int(len(X)),
        "label_balance_up": round(float(y.mean()), 6) if len(y) else None,
        "label": label_config(
            label_mode=str(args.label_mode or DEFAULT_LABEL_MODE),
            target_return_pct=float(args.target_return_pct),
            stop_return_pct=float(args.stop_return_pct),
        ),
        "setup": setup_config(setup_mode=str(args.setup_mode or DEFAULT_SETUP_MODE)),
        "feature_version": str(args.feature_version),
    }
    return X, y, metadata


def main() -> int:
    _validate_feature_groups()

    parser = argparse.ArgumentParser(description="Run feature-group ablation against the current MCL AI training pipeline")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--timeframe", default="1d")
    parser.add_argument("--lookback-years", type=int, default=5)
    parser.add_argument("--horizon", type=int, default=1)
    parser.add_argument(
        "--feature-version",
        default="v3_amd_cycle_state",
        choices=["v3_amd_cycle_state", "v4_layered_execution", "v5_unified_elliott_cycle"],
        help="Feature schema to evaluate. v5_unified_elliott_cycle extends v4 with Elliott wave-cycle-angle-astro-phase features.",
    )
    parser.add_argument(
        "--setup-mode",
        default=DEFAULT_SETUP_MODE,
            choices=["all_bars", "triggered_trade", "london_sweep_mss_buy", "buy_trigger_candidate", "sell_trigger_candidate"],
        help="Filter the dataset to a specific setup before training and ablation.",
    )
    parser.add_argument(
        "--label-mode",
        default=DEFAULT_LABEL_MODE,
        choices=["trend_up", "first_touch_buy", "first_touch_sell"],
        help="Label contract to evaluate. Directional first-touch labels measure realized long or short follow-through instead of next-state trend.",
    )
    parser.add_argument(
        "--target-return-pct",
        type=float,
        default=DEFAULT_TARGET_RETURN_PCT,
        help="Target return threshold for 'first_touch_buy' labels, expressed as decimal return.",
    )
    parser.add_argument(
        "--stop-return-pct",
        type=float,
        default=DEFAULT_STOP_RETURN_PCT,
        help="Stop threshold for 'first_touch_buy' labels, expressed as decimal return.",
    )
    parser.add_argument("--news-file", default="data/news_data_v2.csv")
    parser.add_argument(
        "--astro-file",
        nargs="*",
        default=[
            "data/astro_nakshatra_events_2000_2026.csv",
            "data/gann_moon_aspects_2000_2026.csv",
            "data/gann_cycles_nodes_2000_2026.csv",
            "data/akshaya_tritiya_events_2000_2026.csv",
        ],
    )
    parser.add_argument(
        "--direct-table",
        default="data/reports/gann_astro_25y_ai_training_table.csv",
    )
    parser.add_argument(
        "--master-cycles",
        default="data/reports/master_cycles_25y.csv",
    )
    parser.add_argument(
        "--groups",
        default=None,
        help="Comma-separated subset of feature groups to ablate. Default: all groups.",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Optional path to persist the JSON report.",
    )
    args = parser.parse_args()

    selected_groups = _resolve_groups(args.groups)
    X, y, metadata = _load_memory_dataset(args)
    baseline = _evaluate_dataset(X, y)
    if not baseline.get("trained"):
        print(json.dumps({"trained": False, "reason": baseline.get("reason"), **metadata}, indent=2))
        return 1

    ablations = []
    groups_catalog = {**FEATURE_GROUPS, **LAYERED_GROUPS}
    for group_name in selected_groups:
        feature_names = [name for name in groups_catalog[group_name] if name in feature_names_for_version(args.feature_version)]
        if not feature_names:
            continue
        ablated = _evaluate_dataset(
            X=_mask_columns(X, _feature_indexes_for_version(args.feature_version, feature_names)),
            y=y,
        )
        row = {
            "group": group_name,
            "feature_count": len(feature_names),
            "masked_features": feature_names,
            "mask_strategy": "zero_fill",
            **ablated,
        }
        if ablated.get("trained"):
            row["delta_vs_baseline"] = _delta_metrics(baseline, ablated)
        ablations.append(row)

    ablations.sort(
        key=lambda item: (
            -float((item.get("delta_vs_baseline") or {}).get("delta_brier") or 0.0),
            float((item.get("delta_vs_baseline") or {}).get("delta_accuracy") or 0.0),
        )
    )

    report = {
        "trained": True,
        "feature_version": str(args.feature_version),
        "mask_strategy": "zero_fill",
        "timeframe": str(args.timeframe).lower(),
        "lookback_years": int(args.lookback_years),
        "horizon": int(args.horizon),
        "groups_tested": selected_groups,
        **metadata,
        "baseline": baseline,
        "ablations": ablations,
    }

    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())