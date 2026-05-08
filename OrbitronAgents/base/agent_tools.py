"""Tool definitions and interfaces for Orbitron agents."""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Union


# Type alias for tool handler functions
ToolHandler = Callable[[dict[str, Any]], Any]


@dataclass
class ToolDefinition:
    """Definition of a tool with its schema."""
    name: str
    description: str
    schema: dict[str, Any]
    tags: list[str] = field(default_factory=list)

    def to_ollama_format(self) -> dict[str, Any]:
        """Convert to Ollama tool format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.schema,
            },
        }

    def __hash__(self) -> int:
        return hash(self.name)


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    result: Any = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "success": self.success,
        }
        if self.success:
            result["result"] = self.result
        else:
            result["error"] = self.error
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    def __str__(self) -> str:
        if self.success:
            return f"ToolResult(ok=True, result={self.result!r})"
        return f"ToolResult(ok=False, error={self.error!r})"


class ToolRegistry:
    """Central registry for tools across all agents.

    Allows looking up tools by name and executing them without
    needing direct agent references.
    """

    _instance: Optional["ToolRegistry"] = None

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: dict[str, tuple[ToolDefinition, ToolHandler]] = {}
            cls._instance._agent_map: dict[str, str] = {}  # tool_name -> agent_name
        return cls._instance

    def register(
        self,
        agent_name: str,
        definition: ToolDefinition,
        handler: ToolHandler,
    ) -> None:
        """Register a tool from an agent."""
        self._tools[definition.name] = (definition, handler)
        self._agent_map[definition.name] = agent_name

    def unregister(self, tool_name: str) -> bool:
        """Unregister a tool. Returns True if it was registered."""
        if tool_name in self._tools:
            del self._tools[tool_name]
            del self._agent_map[tool_name]
            return True
        return False

    def unregister_agent(self, agent_name: str) -> list[str]:
        """Unregister all tools from an agent. Returns list of unregistered tool names."""
        unregistered = [
            name for name, agent in self._agent_map.items()
            if agent == agent_name
        ]
        for name in unregistered:
            self.unregister(name)
        return unregistered

    def get_definition(self, tool_name: str) -> Optional[ToolDefinition]:
        """Get tool definition by name."""
        if tool_name in self._tools:
            return self._tools[tool_name][0]
        return None

    def get_handler(self, tool_name: str) -> Optional[ToolHandler]:
        """Get tool handler by name."""
        if tool_name in self._tools:
            return self._tools[tool_name][1]
        return None

    def execute(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Execute a tool by name."""
        if tool_name not in self._tools:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name}",
            )

        definition, handler = self._tools[tool_name]
        try:
            result = handler(args)
            return ToolResult(
                success=True,
                result=result,
                metadata={"tool": tool_name, "agent": self._agent_map[tool_name]},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                metadata={"tool": tool_name, "agent": self._agent_map[tool_name]},
            )

    def list_tools(self) -> list[dict[str, Any]]:
        """List all registered tools."""
        return [
            {
                "name": name,
                "agent": self._agent_map[name],
                "description": defn.description,
                "tags": defn.tags,
            }
            for name, (defn, _) in self._tools.items()
        ]

    def get_all_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in Ollama format."""
        return [defn.to_ollama_format() for defn, _ in self._tools.values()]

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()
        self._agent_map.clear()
