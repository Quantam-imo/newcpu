from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_REG_DIR = Path("data/ai_models")
_LATEST_PTR = _REG_DIR / "latest.json"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ensure_dir() -> None:
    _REG_DIR.mkdir(parents=True, exist_ok=True)


def save_model_bundle(bundle: dict[str, Any], tag: str = "baseline") -> dict[str, Any]:
    _ensure_dir()
    version = f"{tag}-{_utc_stamp()}"
    path = _REG_DIR / f"{version}.json"
    payload = {"version": version, "created_at_utc": _utc_stamp(), **bundle}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _LATEST_PTR.write_text(json.dumps({"version": version, "path": str(path)}, indent=2), encoding="utf-8")
    return {"version": version, "path": str(path)}


def list_versions() -> list[str]:
    if not _REG_DIR.exists():
        return []
    versions = []
    for file in sorted(_REG_DIR.glob("*.json")):
        if file.name == _LATEST_PTR.name:
            continue
        versions.append(file.stem)
    return versions


def load_bundle_by_version(version: str) -> dict[str, Any] | None:
    path = _REG_DIR / f"{version}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_latest_bundle() -> dict[str, Any] | None:
    if not _LATEST_PTR.exists():
        return None
    try:
        ptr = json.loads(_LATEST_PTR.read_text(encoding="utf-8"))
    except Exception:
        return None
    version = str(ptr.get("version") or "").strip()
    if not version:
        return None
    return load_bundle_by_version(version)


def rollback_to_version(version: str) -> bool:
    bundle = load_bundle_by_version(version)
    if not bundle:
        return False
    _LATEST_PTR.write_text(
        json.dumps({"version": version, "path": str(_REG_DIR / f"{version}.json")}, indent=2),
        encoding="utf-8",
    )
    return True
