"""OpenCode Skill for the Executor Agent.

NOTE: Command execution tools (execute_command, execute_python) have been removed
because they duplicate the kernel's `run_command` tool which is registered via
AutonomousAgent.register_command_tool(). The kernel tool is more robust, has better
timeout handling, and provides structured error output with error classification.

This skill is kept for backward compatibility but no longer registers duplicate tools.
"""

import logging
from pathlib import Path
from typing import Any

from .skill_base import ExecutorSkill

logger = logging.getLogger("Executor.OpenCodeSkill")


class OpenCodeSkill(ExecutorSkill):
    """Skill for executing open code and system commands.

    NOTE: Command execution tools are now provided by the kernel via
    AutonomousAgent.register_command_tool(). This skill is kept for backward
    compatibility but no longer registers duplicate tools.
    """

    def __init__(self, workspace: str | None = None):
        super().__init__(
            name="opencode",
            description="Execute code snippets and system commands (tools provided by kernel)",
        )
        if workspace:
            self.set_workspace(workspace)
        # No tools registered — command execution is provided by the kernel
        # via AutonomousAgent.register_command_tool() which is called in _setup_autonomous_agent()
        logger.info("[OpenCodeSkill] Initialized — command tools provided by kernel, no duplicates registered")