"""Skills module for Executor Agent.

Contains all skill implementations for the Executor:
- ProgrammingSkill: File operations and code generation
- WordSkill: Document creation
- OpenCodeSkill: Code and command execution
"""

from .programming import ProgrammingSkill
from .word import WordSkill
from .opencode import OpenCodeSkill
from .skill_base import ExecutorSkill

__all__ = [
    "ProgrammingSkill",
    "WordSkill",
    "OpenCodeSkill",
    "ExecutorSkill",
]
