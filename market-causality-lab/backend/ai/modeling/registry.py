from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_REG_DIR = Path("data/ai_models")
_LATEST_PTR = _REG_DIR / "latest.json"


def _normalize_scope(scope: str | None) -> str | None:
    raw = str(scope or "").strip().lower()
    if not raw:
        return None
    safe = "".join(ch if ch.isalnum() else "_" for ch in raw).strip("_")
    return safe or None


def _latest_ptr_for_scope(scope: str | None) -> Path:
    norm = _normalize_scope(scope)
    if not norm:
        return _LATEST_PTR
    return _REG_DIR / f"latest_{norm}.json"


def _write_ptr(scope: str | None, version: str, path: Path) -> None:
    ptr_path = _latest_ptr_for_scope(scope)
    if ptr_path == _LATEST_PTR:
        return
    ptr_path.write_text(json.dumps({"version": version, "path": str(path)}, indent=2), encoding="utf-8")


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _ensure_dir() -> None:
    _REG_DIR.mkdir(parents=True, exist_ok=True)


def save_model_bundle(
    bundle: dict[str, Any],
    tag: str = "baseline",
    scope: str | None = None,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    _ensure_dir()
    version = f"{tag}-{_utc_stamp()}"
    path = _REG_DIR / f"{version}.json"
    normalized_aliases: list[str] = []
    for alias in aliases or []:
        norm_alias = _normalize_scope(alias)
        if norm_alias and norm_alias not in normalized_aliases:
            normalized_aliases.append(norm_alias)
    payload = {
        "version": version,
        "created_at_utc": _utc_stamp(),
        **bundle,
        "scope_aliases": normalized_aliases,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _LATEST_PTR.write_text(json.dumps({"version": version, "path": str(path)}, indent=2), encoding="utf-8")
    primary_scope = scope or payload.get("model_scope") or payload.get("timeframe")
    _write_ptr(primary_scope, version, path)
    for alias in normalized_aliases:
        _write_ptr(alias, version, path)
    return {"version": version, "path": str(path), "scope": _normalize_scope(scope)}


def list_versions() -> list[str]:
    if not _REG_DIR.exists():
        return []
    versions = []
    for file in sorted(_REG_DIR.glob("*.json")):
        if file.name.startswith("latest"):
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


def load_latest_bundle(scope: str | None = None) -> dict[str, Any] | None:
    norm_scope = _normalize_scope(scope)
    ptr_path = _latest_ptr_for_scope(scope)
    if not ptr_path.exists() and ptr_path != _LATEST_PTR:
        ptr_path = _LATEST_PTR
    if not ptr_path.exists():
        return None
    try:
        ptr = json.loads(ptr_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    version = str(ptr.get("version") or "").strip()
    if not version:
        return None
    bundle = load_bundle_by_version(version)
    if bundle is not None and norm_scope:
        if not bundle.get("timeframe"):
            bundle["timeframe"] = norm_scope
        if not bundle.get("model_scope"):
            bundle["model_scope"] = norm_scope
    return bundle


def rollback_to_version(version: str) -> bool:
    bundle = load_bundle_by_version(version)
    if not bundle:
        return False
    payload = json.dumps({"version": version, "path": str(_REG_DIR / f"{version}.json")}, indent=2)
    _LATEST_PTR.write_text(payload, encoding="utf-8")
    primary_scope = bundle.get("model_scope") or bundle.get("timeframe")
    _write_ptr(primary_scope, version, _REG_DIR / f"{version}.json")
    for alias in bundle.get("scope_aliases") or []:
        _write_ptr(alias, version, _REG_DIR / f"{version}.json")
    return True
