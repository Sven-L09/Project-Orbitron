"""Orbitron Message System - Package initialization.

This package provides the messaging infrastructure for agent communication
in the Orbitron system.
"""

from .message_types import (
    Message,
    MessageHeader,
    MessageType,
    MessagePriority,
    AgentRole,
    PlanningRequest,
    PlanningResponse,
    CommandMessage,
    CommandResult,
    StatusMessage,
    ErrorMessage,
)

from .message_bus import (
    MessageBus,
    get_message_bus,
    reset_message_bus,
)

from .agent_api import (
    AgentCommunicator,
    OrchestratorCommunicator,
    PlannerCommunicator,
    ExecutorCommunicator,
    create_orchestrator_communicator,
    create_planner_communicator,
    create_executor_communicator,
    create_agent_communicator,
)

from .orchestrator_planner_bridge import OrchestratorPlannerBridge
from .orchestrator_executor_bridge import OrchestratorExecutorBridge, ExecutorMessageHandler

__all__ = [
    # Message types
    "Message",
    "MessageHeader",
    "MessageType",
    "MessagePriority",
    "AgentRole",
    "PlanningRequest",
    "PlanningResponse",
    "CommandMessage",
    "CommandResult",
    "StatusMessage",
    "ErrorMessage",
    # Message bus
    "MessageBus",
    "get_message_bus",
    "reset_message_bus",
    # Agent API
    "AgentCommunicator",
    "OrchestratorCommunicator",
    "PlannerCommunicator",
    "ExecutorCommunicator",
    "create_orchestrator_communicator",
    "create_planner_communicator",
    "create_executor_communicator",
    "create_agent_communicator",
    # Bridges
    "OrchestratorPlannerBridge",
    "OrchestratorExecutorBridge",
    "ExecutorMessageHandler",
]

__version__ = "1.0.0"
