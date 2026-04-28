#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Set data/ai_models/latest.json to best current first-touch model by brier (tie: higher accuracy)."
    )
    parser.add_argument("--models-dir", default="data/ai_models", help="Directory containing latest_*.json pointers and model bundles")
    parser.add_argument("--dry-run", action="store_true", help="Compute best candidate but do not write latest.json")
    args = parser.parse_args()

    models_dir = Path(args.models_dir)
    if not models_dir.exists():
        print(f"[fallback] models dir missing: {models_dir}")
        return 1

    best = None
    best_info = None

    for pointer in sorted(models_dir.glob("latest_*first_touch*.json")):
        ptr = _load_json(pointer)
        if not ptr:
            continue

        version = str(ptr.get("version") or "")
        if not version:
            continue

        bundle_path = models_dir / f"{version}.json"
        bundle = _load_json(bundle_path)
        if not bundle:
            continue

        vm = bundle.get("validation_metrics") or {}
        brier = vm.get("brier")
        acc = vm.get("accuracy")
        try:
            brier_f = float(brier)
        except Exception:
            continue
        try:
            acc_f = float(acc)
        except Exception:
            acc_f = 0.0

        key = (brier_f, -acc_f, version)
        if best is None or key < best:
            best = key
            best_info = {
                "pointer": pointer.name,
                "version": version,
                "path": f"data/ai_models/{version}.json",
                "brier": brier_f,
                "accuracy": acc_f,
                "timeframe": bundle.get("timeframe"),
                "setup": (bundle.get("setup") or {}).get("setup_mode"),
                "label": (bundle.get("label") or {}).get("label_mode"),
            }

    if not best_info:
        print("[fallback] no valid first-touch candidates found")
        return 1

    target_latest = {
        "version": best_info["version"],
        "path": best_info["path"],
    }

    latest_path = models_dir / "latest.json"
    current = _load_json(latest_path) or {}
    changed = current != target_latest

    print(
        "[fallback] best candidate: "
        f"pointer={best_info['pointer']} version={best_info['version']} "
        f"brier={best_info['brier']:.6f} accuracy={best_info['accuracy']:.6f} "
        f"tf={best_info['timeframe']} setup={best_info['setup']} label={best_info['label']}"
    )

    if args.dry_run:
        print(f"[fallback] dry-run: latest.json {'would update' if changed else 'already optimal'}")
        return 0

    latest_path.write_text(json.dumps(target_latest, indent=2) + "\n", encoding="utf-8")
    print(f"[fallback] latest.json {'updated' if changed else 'confirmed'} -> {target_latest['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
