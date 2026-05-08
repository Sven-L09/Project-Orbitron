"""OpenCode Skill for the Executor Agent.

Provides code execution and system command capabilities.
"""

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger("Executor.OpenCodeSkill")


from .skill_base import ExecutorSkill

class OpenCodeSkill(ExecutorSkill):
    """Skill for executing open code and system commands.

    Note: This class does NOT inherit from ExecutorSkill to avoid
    circular dependencies. It's used directly by ExecutorAgent.
    """

    def __init__(self, workspace: str | None = None):
        self.name = "opencode"
        self.description = "Execute code snippets and system commands"
        self.workspace = workspace
        self._tools: list[dict[str, Any]] = []
        self._handlers: dict[str, Any] = {}
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Register open code tools."""

        # Tool: Execute Python code
        self.register_tool(
            "execute_python",
            {
                "description": "Execute Python code safely",
                "parameters": {
                    "type": "object",
                    "required": ["code"],
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Python code to execute"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds (default: 30)"
                        }
                    }
                }
            },
            self._handle_execute_python
        )

        # Tool: Execute shell command
        self.register_tool(
            "execute_command",
            {
                "description": "Execute a shell command",
                "parameters": {
                    "type": "object",
                    "required": ["command"],
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute"
                        },
                        "timeout": {
                            "type": "integer",
                            "description": "Timeout in seconds (default: 60)"
                        }
                    }
                }
            },
            self._handle_execute_command
        )

    def register_tool(self, name: str, schema: dict[str, Any], handler: Any) -> None:
        """Register a tool with its schema and handler."""
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

    def set_workspace(self, workspace: str) -> None:
        """Set the workspace directory for file operations."""
        self.workspace = workspace

    def _handle_execute_python(self, args: dict[str, Any]) -> str:
        """Handle execute_python tool call."""
        try:
            code = args.get("code", "")
            timeout = args.get("timeout", 30)

            if not code:
                return json.dumps({"ok": False, "error": "Code is required"})

            # Create temporary Python file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
                f.write(code)
                temp_file = f.name

            try:
                # Execute Python code
                result = subprocess.run(
                    ["python", temp_file],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self.workspace if self.workspace else None,
                )

                return json.dumps({
                    "ok": result.returncode == 0,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "returncode": result.returncode
                })
            finally:
                os.unlink(temp_file)

        except subprocess.TimeoutExpired:
            return json.dumps({
                "ok": False,
                "error": "Command timed out",
                "timeout": timeout
            })
        except Exception as e:
            logger.exception("[OpenCodeSkill] execute_python failed")
            return json.dumps({"ok": False, "error": str(e)})

    def _handle_execute_command(self, args: dict[str, Any]) -> str:
        """Handle execute_command tool call."""
        try:
            command = args.get("command", "")
            timeout = args.get("timeout", 60)

            if not command:
                return json.dumps({"ok": False, "error": "Command is required"})

            # Execute command
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.workspace if self.workspace else None,
            )

            return json.dumps({
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            })

        except subprocess.TimeoutExpired:
            return json.dumps({
                "ok": False,
                "error": "Command timed out",
                "timeout": timeout
            })
        except Exception as e:
            logger.exception("[OpenCodeSkill] execute_command failed")
            return json.dumps({"ok": False, "error": str(e)})
