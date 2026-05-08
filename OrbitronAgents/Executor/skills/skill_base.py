"""Base class for Executor skills."""

import json
from pathlib import Path
from typing import Any, Optional


class ExecutorSkill:
    """Base skill class for executor capabilities.

    Each skill provides specific capabilities like programming, word processing,
    or open code execution.
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.workspace: Optional[str] = None
        self._tools: list[dict[str, Any]] = []
        self._handlers: dict[str, Any] = {}

    def set_workspace(self, workspace: str) -> None:
        """Set the workspace directory for file operations."""
        self.workspace = workspace

    def register_tool(self, name: str, schema: dict[str, Any], handler: Any) -> None:
        """Register a tool with its schema and handler function."""
        self._tools.append({
            "type": "function",
            "function": {
                "name": name,
                **schema
            }
        })
        self._handlers[name] = handler

    def get_tools(self) -> list[dict[str, Any]]:
        """Get all tool schemas for this skill."""
        return self._tools

    def get_handlers(self) -> dict[str, Any]:
        """Get all tool handlers for this skill."""
        return self._handlers

    def _resolve_path(self, path: str) -> Path:
        """Resolve a relative path inside the workspace root."""
        if not self.workspace:
            raise ValueError("Workspace is not configured")

        if not isinstance(path, str) or not path.strip():
            raise ValueError("Path must be a non-empty string")

        p = Path(path)
        workspace_root = Path(self.workspace).resolve()

        if p.is_absolute():
            resolved = p.resolve()
            try:
                resolved.relative_to(workspace_root)
            except ValueError as exc:
                raise ValueError("Path escapes workspace") from exc
            return resolved

        resolved = (workspace_root / p).resolve()

        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError("Path escapes workspace") from exc

        return resolved
