"""Executor Agent Package.

The Executor Agent is the "doer" of the Orbitron system.
It executes plans created by the Planner Agent using specialized skills.

Skills:
- Programming: Code generation, file operations, directory management
- Word: Document creation, reports, text processing
- OpenCode: Python execution, shell commands

The Executor focuses on implementation, not planning.
It reports results back to the Orchestrator for validation.
"""

from .ExecutorAgent import (
    ExecutorAgent,
    create_executor_agent,
)

from .execution_state import ExecutionState, StepResult, FileRecord
from .skills.skill_base import ExecutorSkill

# Re-export skills from skills module for backwards compatibility
from .skills import ProgrammingSkill, WordSkill, OpenCodeSkill

__all__ = [
    "ExecutorAgent",
    "create_executor_agent",
    "ExecutionState",
    "StepResult",
    "FileRecord",
    "ExecutorSkill",
    "ProgrammingSkill",
    "WordSkill",
    "OpenCodeSkill",
]
