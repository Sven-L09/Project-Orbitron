"""Programming Skill for the Executor Agent.

NOTE: Most file operation tools (create_file, read_file, list_directory, etc.)
are now provided directly by the kernel via the AutonomousAgent's register_file_tools().
This skill is kept for backward compatibility but its duplicate tools have been removed.
The kernel tools should be preferred as they are more robust and properly integrated.
"""

import json
import logging
from pathlib import Path
from typing import Any

from .skill_base import ExecutorSkill

logger = logging.getLogger("Executor.ProgrammingSkill")


class ProgrammingSkill(ExecutorSkill):
    """Skill for programming tasks.

    NOTE: File operation tools (create_file, modify_file, read_file, list_directory)
    are now provided by the kernel via AutonomousAgent.register_file_tools().
    This skill is kept for backward compatibility but no longer registers duplicate tools.
    The kernel tools are more robust and properly integrated with the autonomous agent loop.
    """

    def __init__(self):
        super().__init__(
            name="programming",
            description="Code generation, modification, and programming tasks (tools provided by kernel)"
        )
        # No tools registered — all file operations are provided by the kernel
        # via AutonomousAgent.register_file_tools() which is called in _setup_autonomous_agent()
        logger.info("[ProgrammingSkill] Initialized — file tools provided by kernel, no duplicates registered")
