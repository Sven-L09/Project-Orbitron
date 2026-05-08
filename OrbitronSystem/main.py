"""OrbitronSystem entrypoint (runs services forever).

This is the main entry point for the Orbitron System.
It initializes and runs all components including:
- MessageBus for agent communication
- Orchestrator for task management
- Planner for planning
- Kernel for code execution
- TelegramBot for user interaction
"""

import os
import sys
from pathlib import Path


def _bootstrap_sys_path() -> None:
    """Add project root to sys.path for imports."""
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_dotenv() -> None:
    """Load environment variables from .env file."""
    candidate_paths: list[Path] = []
    try:
        candidate_paths.append(Path(__file__).resolve().parents[1] / ".env")
    except Exception:
        pass
    candidate_paths.append(Path.cwd() / ".env")

    for env_path in candidate_paths:
        if not env_path.exists() or not env_path.is_file():
            continue
        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not key:
                    continue
                os.environ.setdefault(key, value)
        except Exception:
            continue


def main() -> None:
    """Main entry point."""
    _bootstrap_sys_path()
    _load_dotenv()
    
    # Import and start the ServiceSystem
    from OrbitronSystem.ServiceSystem import ServiceSystem
    
    # Create and run service system
    system = ServiceSystem(
        enable_telegram=True,
        max_planning_iterations=3,
    )
    
    system.run_forever()


if __name__ == "__main__":
    main()
