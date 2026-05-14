"""Orbitron Agents Package.

This package contains specialized agents for the Orbitron system:
- Orchestrator: Central coordinator and task manager
- Planner: Strategic planning and task decomposition
- Executor: Plan execution and implementation
- Tester: Critical quality assurance and testing
- Base: Abstract base classes and utilities
"""

from .Orchestrator import (
    TaskOrchestrator,
    Task,
    TaskStatus,
    PlanReviewResult,
    create_orchestrator,
    Orchestrator,
    ReflectionEngine,
)

from .Planner import (
    PlannerAgent,
    PlannerSkill,
    create_planner_agent,
    create_skill,
)

from .Executor import (
    ExecutorAgent,
    create_executor_agent,
    ExecutionState,
)

from .Tester import (
    TesterAgent,
    create_tester_agent,
)

from .base import (
    AgentBase,
    AgentState,
    AgentContext,
    ContextScope,
    ToolDefinition,
    ToolHandler,
    ToolResult,
    ToolRegistry,
    AutonomousAgent,
    AgentLoopResult,
)

__all__ = [
    # Orchestrator
    "TaskOrchestrator",
    "Task",
    "TaskStatus",
    "PlanReviewResult",
    "create_orchestrator",
    "Orchestrator",
    "ReflectionEngine",
    # Planner
    "PlannerAgent",
    "PlannerSkill",
    "create_planner_agent",
    "create_skill",
    # Executor
    "ExecutorAgent",
    "create_executor_agent",
    "ExecutionState",
    # Tester
    "TesterAgent",
    "create_tester_agent",
    # Base
    "AgentBase",
    "AgentState",
    "AgentContext",
    "ContextScope",
    "ToolDefinition",
    "ToolHandler",
    "ToolResult",
    "ToolRegistry",
    "AutonomousAgent",
    "AgentLoopResult",
]
