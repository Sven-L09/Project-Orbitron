"""OpenCode Skill for the Executor Agent.

Provides code execution and system command capabilities.
"""

import json
import logging
import os
import subprocess
import tempfile
from typing import Any

from .skill_base import ExecutorSkill

logger = logging.getLogger("Executor.OpenCodeSkill")


class OpenCodeSkill(ExecutorSkill):
    """Skill for executing open code and system commands."""

    def __init__(self, workspace: str | None = None):
        super().__init__(
            name="opencode",
            description="Execute code snippets and system commands",
        )
        if workspace:
            self.set_workspace(workspace)
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