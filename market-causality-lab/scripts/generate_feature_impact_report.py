#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Ensure repository root is importable when executed as scripts/.. path.
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.ai.modeling.feature_pipeline import LAYERED_FEATURE_NAMES

NAMED_ASPECT_FEATURES = [
    "news_aspect_event_count",
    "news_conjunction_count",
    "news_square_count",
    "news_opposition_count",
    "news_trine_count",
    "news_sextile_count",
    "news_ingress_event_count",
    "news_nakshatra_event_count",
    "news_gann_event_count",
    "news_eclipse_event_count",
]


@dataclass
class ModelSummary:
    pointer: str
    version: str
    timeframe: str
    setup_mode: str
    label_mode: str
    model_name: str
    brier: float | None
    accuracy: float | None
    log_loss: float | None
    top10: list[tuple[str, float, int]]
    named_aspects: list[tuple[str, float, int]]
    skipped_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "pointer": self.pointer,
            "version": self.version,
            "timeframe": self.timeframe,
            "setup_mode": self.setup_mode,
            "label_mode": self.label_mode,
            "model_name": self.model_name,
            "brier": self.brier,
            "accuracy": self.accuracy,
            "log_loss": self.log_loss,
            "top10": [
                {"feature": name, "weight": float(w), "rank": int(rank), "abs_weight": abs(float(w))}
                for name, w, rank in self.top10
            ],
            "named_aspects": [
                {"feature": name, "weight": float(w), "rank": int(rank), "abs_weight": abs(float(w))}
                for name, w, rank in self.named_aspects
            ],
            "skipped_reason": self.skipped_reason,
        }


def _safe_float(v) -> float | None:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _iter_scope_pointers(models_dir: Path) -> Iterable[Path]:
    yield from sorted(models_dir.glob("latest_*first_touch*.json"))


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _rank_weights(weights: list[float]) -> tuple[list[tuple[str, float, int]], dict[str, tuple[float, int]]]:
    pairs = [(name, float(w)) for name, w in zip(LAYERED_FEATURE_NAMES, weights)]
    ranked = sorted(pairs, key=lambda x: abs(x[1]), reverse=True)
    rank_map: dict[str, tuple[float, int]] = {}
    for idx, (name, w) in enumerate(ranked, start=1):
        rank_map[name] = (w, idx)
    return ranked, rank_map


def summarize_pointer(pointer_path: Path, models_dir: Path) -> ModelSummary | None:
    ptr = _load_json(pointer_path)
    if not ptr:
        return None

    version = str(ptr.get("version") or "")
    bundle_path = models_dir / f"{version}.json"
    bundle = _load_json(bundle_path)
    if not bundle:
        return None

    setup_mode = str((bundle.get("setup") or {}).get("setup_mode") or "")
    label_mode = str((bundle.get("label") or {}).get("label_mode") or "")
    timeframe = str(bundle.get("timeframe") or "")

    vm = bundle.get("validation_metrics") or {}
    brier = _safe_float(vm.get("brier"))
    accuracy = _safe_float(vm.get("accuracy"))
    log_loss = _safe_float(vm.get("log_loss"))

    best_model = bundle.get("best_model") or {}
    model_name = str(best_model.get("name") or "")

    if model_name != "logistic_gd":
        return ModelSummary(
            pointer=pointer_path.name,
            version=version,
            timeframe=timeframe,
            setup_mode=setup_mode,
            label_mode=label_mode,
            model_name=model_name,
            brier=brier,
            accuracy=accuracy,
            log_loss=log_loss,
            top10=[],
            named_aspects=[],
            skipped_reason="best_model_not_logistic",
        )

    serialized = best_model.get("serialized") or {}
    weights = serialized.get("w")
    if not isinstance(weights, list) or len(weights) != len(LAYERED_FEATURE_NAMES):
        return ModelSummary(
            pointer=pointer_path.name,
            version=version,
            timeframe=timeframe,
            setup_mode=setup_mode,
            label_mode=label_mode,
            model_name=model_name,
            brier=brier,
            accuracy=accuracy,
            log_loss=log_loss,
            top10=[],
            named_aspects=[],
            skipped_reason="weight_vector_missing_or_mismatch",
        )

    ranked, rank_map = _rank_weights(weights)
    top10 = [(name, w, i + 1) for i, (name, w) in enumerate(ranked[:10])]

    named = []
    for fname in NAMED_ASPECT_FEATURES:
        w, r = rank_map.get(fname, (0.0, -1))
        named.append((fname, w, r))

    return ModelSummary(
        pointer=pointer_path.name,
        version=version,
        timeframe=timeframe,
        setup_mode=setup_mode,
        label_mode=label_mode,
        model_name=model_name,
        brier=brier,
        accuracy=accuracy,
        log_loss=log_loss,
        top10=top10,
        named_aspects=named,
        skipped_reason=None,
    )


def render_markdown(summaries: list[ModelSummary]) -> str:
    now = datetime.now(timezone.utc)
    lines: list[str] = []
    lines.append(f"# Feature Impact Report ({now.strftime('%Y-%m-%d')})")
    lines.append("")
    lines.append("Auto-generated from current latest first-touch model pointers.")
    lines.append("Weight impact uses absolute logistic coefficients on standardized features.")
    lines.append("")

    if not summaries:
        lines.append("No valid model summaries were found.")
        return "\n".join(lines) + "\n"

    lines.append("## Snapshot")
    lines.append("")
    lines.append("| Scope Pointer | Version | TF | Setup | Label | Model | Brier | Accuracy |")
    lines.append("|---|---|---|---|---|---|---:|---:|")
    for s in summaries:
        brier = "n/a" if s.brier is None else f"{s.brier:.6f}"
        acc = "n/a" if s.accuracy is None else f"{s.accuracy:.6f}"
        lines.append(
            f"| {s.pointer} | {s.version} | {s.timeframe} | {s.setup_mode} | {s.label_mode} | {s.model_name} | {brier} | {acc} |"
        )
    lines.append("")

    for s in summaries:
        lines.append(f"## {s.timeframe} / {s.setup_mode} / {s.label_mode}")
        lines.append("")
        lines.append(f"- pointer: {s.pointer}")
        lines.append(f"- version: {s.version}")
        lines.append(f"- model: {s.model_name}")
        if s.brier is not None:
            lines.append(f"- brier: {s.brier:.6f}")
        if s.accuracy is not None:
            lines.append(f"- accuracy: {s.accuracy:.6f}")
        if s.log_loss is not None:
            lines.append(f"- log_loss: {s.log_loss:.6f}")

        if s.skipped_reason:
            lines.append(f"- impact extraction: skipped ({s.skipped_reason})")
            lines.append("")
            continue

        lines.append("")
        lines.append("Top 10 features by |weight|:")
        lines.append("")
        lines.append("| Rank | Feature | Weight | |Weight| |")
        lines.append("|---:|---|---:|---:|")
        for name, w, rank in s.top10:
            lines.append(f"| {rank} | {name} | {w:.6f} | {abs(w):.6f} |")

        lines.append("")
        lines.append("Named aspect features:")
        lines.append("")
        lines.append("| Feature | Rank | Weight | |Weight| |")
        lines.append("|---|---:|---:|---:|")
        for name, w, rank in s.named_aspects:
            rank_txt = "n/a" if rank < 0 else str(rank)
            lines.append(f"| {name} | {rank_txt} | {w:.6f} | {abs(w):.6f} |")
        lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate feature impact report from latest model pointers.")
    parser.add_argument("--models-dir", default="data/ai_models", help="Directory containing model bundles and latest_*.json pointers")
    parser.add_argument("--output-dir", default="data/reports", help="Directory to write report artifacts")
    parser.add_argument("--prefix", default="feature_impact", help="Output report filename prefix")
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[ModelSummary] = []
    for pointer in _iter_scope_pointers(models_dir):
        summary = summarize_pointer(pointer, models_dir)
        if summary is not None:
            summaries.append(summary)

    md = render_markdown(summaries)

    now = datetime.now(timezone.utc)
    payload = {
        "generated_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "models_processed": len(summaries),
        "named_aspect_features": NAMED_ASPECT_FEATURES,
        "summaries": [s.to_dict() for s in summaries],
    }

    date_tag = now.strftime("%Y-%m-%d")
    dated = output_dir / f"{args.prefix}_{date_tag}.md"
    latest = output_dir / f"{args.prefix}_latest.md"
    dated_json = output_dir / f"{args.prefix}_{date_tag}.json"
    latest_json = output_dir / f"{args.prefix}_latest.json"

    dated.write_text(md, encoding="utf-8")
    latest.write_text(md, encoding="utf-8")
    dated_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    latest_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"[feature-impact] wrote {dated}")
    print(f"[feature-impact] wrote {latest}")
    print(f"[feature-impact] wrote {dated_json}")
    print(f"[feature-impact] wrote {latest_json}")
    print(f"[feature-impact] models_processed={len(summaries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
