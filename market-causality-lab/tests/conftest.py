from __future__ import annotations

import sys
from pathlib import Path


def _ensure_project_paths() -> None:
    """Make market-causality-lab packages importable when running pytest from repo root."""
    tests_dir = Path(__file__).resolve().parent
    project_root = tests_dir.parent
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)


_ensure_project_paths()
