"""Shared .env loader for Orbitron.

This module provides a centralized .env file loader that was previously
duplicated in kernel.py, ServiceSystem.py, and main.py.

Usage:
    from OrbitronUtils.dotenv_loader import load_dotenv
    load_dotenv()
"""

import os
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("OrbitronUtils.dotenv")


def load_dotenv(
    env_path: Optional[str | Path] = None,
    overwrite: bool = False,
    search_paths: Optional[list[str | Path]] = None,
) -> bool:
    """Load environment variables from a .env file.

    Minimal .env loader (key=value per line) without external dependencies.

    Args:
        env_path: Explicit path to .env file. If provided, only this file is loaded.
        overwrite: If True, overwrite existing environment variables.
                   If False (default), existing variables are not changed.
        search_paths: Additional paths to search for .env files.
                      Defaults to project root and current working directory.

    Returns:
        True if at least one .env file was loaded successfully, False otherwise.
    """
    candidate_paths: list[Path] = []

    if env_path:
        # Explicit path takes priority
        candidate_paths.append(Path(env_path))
    else:
        # Default search paths
        # 1. Project root (parent of OrbitronKernel)
        try:
            project_root = Path(__file__).resolve().parents[1]
            candidate_paths.append(project_root / ".env")
        except Exception:
            pass

        # 2. Current working directory
        candidate_paths.append(Path.cwd() / ".env")

        # 3. Additional search paths
        if search_paths:
            for path in search_paths:
                candidate_paths.append(Path(path))

    loaded = False

    for env_file in candidate_paths:
        if not env_file.exists() or not env_file.is_file():
            continue

        try:
            line_count = 0
            for raw_line in env_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()

                # Skip empty lines and comments
                if not line or line.startswith("#"):
                    continue

                # Parse key=value
                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")

                if not key:
                    continue

                # Set environment variable
                if overwrite or key not in os.environ:
                    os.environ[key] = value
                    line_count += 1

            loaded = True
            logger.info("[dotenv] Loaded %d variables from %s", line_count, env_file)

        except Exception as e:
            logger.warning("[dotenv] Failed to load %s: %s", env_file, e)

    if not loaded:
        logger.debug("[dotenv] No .env file found in search paths")

    return loaded


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """Get an environment variable with an optional default.

    Args:
        key: Environment variable name
        default: Default value if not set

    Returns:
        The environment variable value, or default if not set
    """
    return os.environ.get(key, default)


def require_env(key: str, description: str = "") -> str:
    """Get a required environment variable, raising an error if not set.

    Args:
        key: Environment variable name
        description: Human-readable description for error messages

    Returns:
        The environment variable value

    Raises:
        EnvironmentError: If the variable is not set
    """
    value = os.environ.get(key)
    if value is None:
        desc = f" ({description})" if description else ""
        raise EnvironmentError(
            f"Required environment variable {key}{desc} is not set. "
            f"Please add it to your .env file."
        )
    return value