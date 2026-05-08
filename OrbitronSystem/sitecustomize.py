"""Project bootstrap for running Orbitron modules from subdirectories."""

from __future__ import annotations

import sys
from pathlib import Path


def _add_project_root() -> None:
    current = Path(__file__).resolve()
    project_root = current.parent.parent

    if (project_root / "OrbitronSystem").is_dir() and (project_root / "OrbitronAgents").is_dir():
        root_str = str(project_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)


_add_project_root()
