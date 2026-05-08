"""Abstract base class for all Orbitron agents."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional

from .agent_context import AgentContext
from .agent_tools import ToolDefinition, ToolHandler, ToolResult


class AgentState(Enum):
    """Possible states for an agent."""
    IDLE = auto()
    INITIALIZING = auto()
    PROCESSING = auto()
    WAITING = auto()
    ERROR = auto()
    SHUTDOWN = auto()


@dataclass
class AgentMetrics:
    """Metrics collected during agent lifetime."""
    tasks_received: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_processing_time_ms: float = 0.0
    last_error: Optional[str] = None
    last_activity: Optional[datetime] = None

    def record_task_start(self) -> None:
        self.tasks_received += 1
        self.last_activity = datetime.now()

    def record_task_complete(self, success: bool, duration_ms: float) -> None:
        if success:
            self.tasks_completed += 1
        else:
            self.tasks_failed += 1
        self.total_processing_time_ms += duration_ms
        self.last_activity = datetime.now()

    def record_error(self, error: str) -> None:
        self.last_error = error
        self.last_activity = datetime.now()

    @property
    def success_rate(self) -> float:
        if self.tasks_received == 0:
            return 0.0
        return self.tasks_completed / self.tasks_received

    @property
    def avg_processing_time_ms(self) -> float:
        completed = self.tasks_completed + self.tasks_failed
        if completed == 0:
            return 0.0
        return self.total_processing_time_ms / completed


class AgentBase(ABC):
    """Abstract base class for all Orbitron agents.

    Provides:
    - Common lifecycle management
    - Context handling
    - Tool registration interface
    - Metrics collection
    - Logging infrastructure
    """

    def __init__(
        self,
        agent_name: str,
        workspace_root: Optional[str] = None,
        context: Optional[AgentContext] = None,
    ):
        self.agent_name = agent_name
        self.workspace_root = Path(workspace_root) if workspace_root else Path.home() / ".orbitron" / "workspace"
        self.workspace_root.mkdir(parents=True, exist_ok=True)

        self._context = context or AgentContext(agent_name=agent_name)
        self._state = AgentState.IDLE
        self._metrics = AgentMetrics()
        self._logger = logging.getLogger(f"Agent.{agent_name}")

        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

        self._logger.info("[AgentBase] %s initialized at %s", agent_name, self.workspace_root)

    # ========== Lifecycle ==========

    def initialize(self) -> bool:
        """Initialize the agent. Called once at startup."""
        try:
            self._state = AgentState.INITIALIZING
            self._logger.info("[AgentBase] Initializing %s...", self.agent_name)

            self._register_tools()
            result = self.on_initialize()

            self._state = AgentState.IDLE
            self._logger.info("[AgentBase] %s initialized successfully", self.agent_name)
            return result
        except Exception as e:
            self._state = AgentState.ERROR
            self._metrics.record_error(str(e))
            self._logger.exception("[AgentBase] Initialization failed")
            return False

    def shutdown(self) -> None:
        """Shutdown the agent. Called once at system stop."""
        try:
            self._state = AgentState.SHUTDOWN
            self._logger.info("[AgentBase] Shutting down %s...", self.agent_name)
            self.on_shutdown()
            self._logger.info("[AgentBase] %s shut down complete", self.agent_name)
        except Exception as e:
            self._logger.exception("[AgentBase] Shutdown error")
        finally:
            self._state = AgentState.SHUTDOWN

    @abstractmethod
    def _register_tools(self) -> None:
        """Register all tools this agent provides."""
        pass

    @abstractmethod
    def on_initialize(self) -> bool:
        """Override to add custom initialization logic."""
        return True

    @abstractmethod
    def on_shutdown(self) -> None:
        """Override to add custom shutdown logic."""
        pass

    # ========== Processing ==========

    def process(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Process input data and return result.

        This is the main entry point for agent work.
        """
        start_time = datetime.now()
        self._state = AgentState.PROCESSING
        self._metrics.record_task_start()

        try:
            result = self._process_impl(input_data)

            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            self._metrics.record_task_complete(success=True, duration_ms=duration_ms)
            self._state = AgentState.IDLE

            return result

        except Exception as e:
            duration_ms = (datetime.now() - start_time).total_seconds() * 1000
            self._metrics.record_error(str(e))
            self._metrics.record_task_complete(success=False, duration_ms=duration_ms)
            self._state = AgentState.ERROR

            self._logger.exception("[AgentBase] Processing failed")
            return {
                "success": False,
                "error": str(e),
                "agent": self.agent_name,
            }

    @abstractmethod
    def _process_impl(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Override to implement agent-specific processing logic."""
        pass

    # ========== Tool Management ==========

    def register_tool(
        self,
        name: str,
        description: str,
        schema: dict[str, Any],
        handler: ToolHandler,
    ) -> None:
        """Register a tool with its schema and handler."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            schema=schema,
        )
        self._handlers[name] = handler
        self._logger.debug("[AgentBase] Registered tool: %s", name)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in Ollama format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.schema,
                },
            }
            for tool in self._tools.values()
        ]

    def execute_tool(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a tool by name with given arguments."""
        if tool_name not in self._handlers:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        try:
            handler = self._handlers[tool_name]
            result = handler(args)
            return ToolResult(
                success=True,
                result=result,
            )
        except Exception as e:
            self._logger.exception("[AgentBase] Tool execution failed: %s", tool_name)
            return ToolResult(
                success=False,
                error=str(e),
            )

    # ========== Context Access ==========

    @property
    def context(self) -> AgentContext:
        """Get the agent's context."""
        return self._context

    def get_context_value(self, key: str, default: Any = None) -> Any:
        """Get a value from context."""
        return self._context.get(key, default)

    def set_context_value(self, key: str, value: Any) -> None:
        """Set a value in context."""
        self._context.set(key, value)

    # ========== State & Metrics ==========

    @property
    def state(self) -> AgentState:
        """Get current agent state."""
        return self._state

    @property
    def metrics(self) -> AgentMetrics:
        """Get agent metrics."""
        return self._metrics

    def get_status(self) -> dict[str, Any]:
        """Get agent status information."""
        return {
            "name": self.agent_name,
            "state": self._state.name,
            "workspace": str(self.workspace_root),
            "tools_registered": len(self._tools),
            "metrics": {
                "tasks_received": self._metrics.tasks_received,
                "tasks_completed": self._metrics.tasks_completed,
                "tasks_failed": self._metrics.tasks_failed,
                "success_rate": self._metrics.success_rate,
                "avg_processing_time_ms": self._metrics.avg_processing_time_ms,
            },
        }
