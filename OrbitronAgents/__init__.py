"""Orbitron Agents Package.

This package contains specialized agents for the Orbitron system:
- Orchestrator: Central coordinator and task manager
- Planner: Strategic planning and task decomposition
- Executor: Plan execution and implementation
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
