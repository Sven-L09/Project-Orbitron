"""OrbitronSystem entrypoint (runs services forever)."""

import os
import sys
from pathlib import Path


def _bootstrap_sys_path() -> None:
    # Add project root so we can import OrbitronKernel.* when running as a script.
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_dotenv() -> None:
    """Minimal .env loader (key=value per line) without external deps."""
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
    _bootstrap_sys_path()
    _load_dotenv()
    from OrbitronSystem.ServiceSystem import ServiceSystem

    system = ServiceSystem()
    system.run_forever()


if __name__ == "__main__":
    main()
