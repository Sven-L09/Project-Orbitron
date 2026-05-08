"""Autonomous agent loop implementation for intelligent tool-calling agents.

This module provides the AutonomousAgent class which implements a multi-turn
conversation loop where the LLM can iteratively invoke tools, observe results,
reason, and decide on the next action.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .agent_tools import ToolDefinition, ToolResult

logger = logging.getLogger("AutonomousAgent")


@dataclass
class AgentLoopResult:
    """Result of an autonomous agent loop."""
    content: str = ""
    done: bool = False
    terminal_tool: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls_made: int = 0
    rounds_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "done": self.done,
            "terminal_tool": self.terminal_tool,
            "metadata": self.metadata,
            "tool_calls_made": self.tool_calls_made,
            "rounds_used": self.rounds_used,
        }


class AutonomousAgent:
    """Base class for agents that run an autonomous tool-calling loop.

    Agents extending this class can register tools, set a system prompt,
    and run tasks where the LLM decides which tools to call and when.

    The loop continues until:
    - The LLM returns no tool calls (natural response)
    - A terminal tool is called (submit_plan, submit_result, ask_question, terminate)
    - max_rounds is reached
    """

    # Tools that terminate the autonomous loop
    TERMINAL_TOOLS = {"submit_plan", "submit_result", "ask_question", "terminate"}

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        kernel=None,
        max_rounds: int = 25,
    ):
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.kernel = kernel
        self.max_rounds = max_rounds
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._logger = logging.getLogger(f"AutonomousAgent.{agent_name}")

    # ========== Tool Management ==========

    def register_tool(
        self,
        name: str,
        description: str,
        schema: dict[str, Any],
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        """Register a tool with its schema and handler."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            schema=schema,
        )
        self._handlers[name] = handler
        self._logger.debug("[%s] Registered tool: %s", self.agent_name, name)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get all tool definitions in Ollama format."""
        return [tool.to_ollama_format() for tool in self._tools.values()]

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
            self._logger.exception("[%s] Tool execution failed: %s", self.agent_name, tool_name)
            return ToolResult(
                success=False,
                error=str(e),
            )

    def _parse_tool_call(self, call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Extract tool name and args from Ollama tool_calls element."""
        fn = call.get("function") or {}
        name = fn.get("name")
        args = fn.get("arguments")
        if not isinstance(name, str) or not name:
            return "unknown_tool", {"error": "Missing tool name"}
        if args is None:
            args = {}
        if not isinstance(args, dict):
            return name, {"error": "Tool arguments must be an object"}
        return name, args

    def _is_terminal_tool(self, tool_name: str) -> bool:
        """Check if a tool call should terminate the loop."""
        return tool_name in self.TERMINAL_TOOLS

    # ========== Autonomous Loop ==========

    def run_task(
        self,
        task_description: str,
        context: Optional[dict[str, Any]] = None,
        max_rounds: Optional[int] = None,
    ) -> AgentLoopResult:
        """Run the autonomous tool-calling loop for a given task.

        Args:
            task_description: The user's request or goal.
            context: Optional additional context (e.g., codebase info, prior plans).
            max_rounds: Override the default max rounds for this task.

        Returns:
            AgentLoopResult with the final content and metadata.
        """
        if not self.kernel:
            return AgentLoopResult(
                content="Error: No kernel provided",
                done=False,
            )

        max_rounds = max_rounds or self.max_rounds
        tools = self.get_tool_definitions()

        # Build initial messages
        user_content = task_description
        if context:
            user_content += f"\n\n## Context\n{json.dumps(context, indent=2, ensure_ascii=False)}"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_content},
        ]

        self._logger.info("[%s] Starting autonomous loop (max_rounds=%d)", self.agent_name, max_rounds)

        total_tool_calls = 0

        for round_num in range(max_rounds):
            try:
                resp = self.kernel.ollama.chat(
                    messages=messages,
                    tools=tools,
                    stream=False,
                )
            except Exception as e:
                self._logger.exception("[%s] LLM call failed", self.agent_name)
                return AgentLoopResult(
                    content=f"Error: LLM call failed: {e}",
                    done=False,
                    rounds_used=round_num,
                    tool_calls_made=total_tool_calls,
                )

            msg = resp.get("message") or {}
            if isinstance(msg, dict):
                messages.append(msg)
            else:
                # Fallback if message is not a dict
                messages.append({"role": "assistant", "content": str(msg)})
                msg = messages[-1]

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                # No tool calls: the LLM is done reasoning
                content = str(msg.get("content") or "")
                self._logger.info("[%s] Loop finished naturally after %d rounds", self.agent_name, round_num + 1)
                return AgentLoopResult(
                    content=content,
                    done=True,
                    rounds_used=round_num + 1,
                    tool_calls_made=total_tool_calls,
                )

        # Execute each tool call
            for call in tool_calls:
                name, args = self._parse_tool_call(call)
                total_tool_calls += 1

                self._logger.info("[%s] Tool call: %s(args=%s)", self.agent_name, name, args)

                result = self.execute_tool(name, args)
                result_dict = result.to_dict()

                # Truncate massive tool results to prevent payload explosion
                result_str = json.dumps(result_dict, ensure_ascii=False)
                max_tool_len = 50000
                if len(result_str) > max_tool_len:
                    self._logger.warning(
                        "[%s] Truncating tool result for '%s' from %d to %d chars",
                        self.agent_name, name, len(result_str), max_tool_len,
                    )
                    result_str = result_str[:max_tool_len] + f"...[truncated — {len(result_str)} chars total]"

                messages.append({
                    "role": "tool",
                    "tool_name": name,
                    "content": result_str,
                })

                if self._is_terminal_tool(name):
                    self._logger.info("[%s] Terminal tool '%s' called after %d rounds", self.agent_name, name, round_num + 1)
                    return AgentLoopResult(
                        content=result_str,
                        done=True,
                        terminal_tool=name,
                        rounds_used=round_num + 1,
                        tool_calls_made=total_tool_calls,
                        metadata={"terminal_result": result_dict},
                    )

        # Max rounds exceeded
        self._logger.warning("[%s] Loop exceeded max rounds (%d)", self.agent_name, max_rounds)
        return AgentLoopResult(
            content=f"Error: Autonomous loop exceeded maximum rounds ({max_rounds})",
            done=False,
            rounds_used=max_rounds,
            tool_calls_made=total_tool_calls,
        )

    # ========== Convenience Methods ==========

    def register_file_tools(self) -> None:
        """Register standard file operation tools from the kernel."""
        if not self.kernel:
            self._logger.warning("[%s] Cannot register file tools: no kernel", self.agent_name)
            return

        # Delegate file operations to kernel
        self.register_tool(
            name="read_file",
            description="Read a file from the workspace.",
            schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                },
            },
            handler=lambda args: self._kernel_file_tool("read_file", args),
        )
        self.register_tool(
            name="create_file",
            description="Create a new file in the workspace.",
            schema={
                "type": "object",
                "required": ["path", "content"],
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "content": {"type": "string", "description": "File contents"},
                    "overwrite": {"type": "boolean", "description": "Overwrite if exists", "default": False},
                },
            },
            handler=lambda args: self._kernel_file_tool("create_file", args),
        )
        self.register_tool(
            name="update_file",
            description="Edit an existing file. Three modes: (1) Find & Replace: provide 'old_content' and 'new_content' to surgically replace a specific section — always read the file first to get exact text. (2) Append: provide 'content' with 'append=true' to add content to the end of a file. (3) Full Overwrite: provide 'content' only — replaces the ENTIRE file. Use ONLY for complete rewrites. IMPORTANT: For editing existing files, prefer Find & Replace or Append to avoid accidentally deleting existing content.",
            schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "content": {"type": "string", "description": "New full file contents (for overwrite mode) or content to append (for append mode)"},
                    "old_content": {"type": "string", "description": "The exact text to find in the file (for find & replace mode). Use read_file first to get exact text."},
                    "new_content": {"type": "string", "description": "The text to replace old_content with (for find & replace mode)"},
                    "append": {"type": "boolean", "description": "If true, append content to end of file instead of overwriting", "default": False},
                },
            },
            handler=lambda args: self._kernel_file_tool("update_file", args),
        )
        self.register_tool(
            name="delete_file",
            description="Delete a file in the workspace.",
            schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "missing_ok": {"type": "boolean", "description": "Do not error if missing", "default": False},
                },
            },
            handler=lambda args: self._kernel_file_tool("delete_file", args),
        )
        self.register_tool(
            name="list_directory",
            description="List a directory in the workspace.",
            schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Relative directory path"},
                },
            },
            handler=lambda args: self._kernel_file_tool("list_directory", args),
        )

    def _kernel_file_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        """Delegate a file tool call to the kernel."""
        result_str = self.kernel._dispatch_tool(tool_name, args)
        try:
            return json.loads(result_str)
        except json.JSONDecodeError:
            return {"ok": True, "raw": result_str}

    def register_search_tool(self) -> None:
        """Register the search_files tool from the kernel."""
        if not self.kernel:
            return
        self.register_tool(
            name="search_files",
            description="Search for files or content matching a pattern in the workspace.",
            schema={
                "type": "object",
                "required": ["pattern"],
                "properties": {
                    "pattern": {"type": "string", "description": "Search pattern or regex"},
                    "path": {"type": "string", "description": "Directory to search in", "default": "."},
                    "file_extension": {"type": "string", "description": "Optional file extension filter (e.g. '.py')"},
                },
            },
            handler=lambda args: self._kernel_file_tool("search_files", args),
        )

    def register_command_tool(self) -> None:
        """Register the run_command tool from the kernel."""
        if not self.kernel:
            return
        self.register_tool(
            name="run_command",
            description="Run a shell command in the workspace. Be careful with destructive operations.",
            schema={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
                    "cwd": {"type": "string", "description": "Working directory (relative to workspace)", "default": "."},
                },
            },
            handler=lambda args: self._kernel_file_tool("run_command", args),
        )

    def register_syntax_tool(self) -> None:
        """Register the check_syntax tool from the kernel."""
        if not self.kernel:
            return
        self.register_tool(
            name="check_syntax",
            description="Check the syntax of a code file.",
            schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"},
                    "language": {"type": "string", "description": "Programming language (e.g. python, javascript)", "default": "python"},
                },
            },
            handler=lambda args: self._kernel_file_tool("check_syntax", args),
        )

    def register_test_tool(self) -> None:
        """Register the run_tests tool from the kernel."""
        if not self.kernel:
            return
        self.register_tool(
            name="run_tests",
            description="Run tests for a module or project.",
            schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string", "description": "Relative path to test file or directory"},
                    "test_pattern": {"type": "string", "description": "Optional test pattern (e.g. 'test_*.py')"},
                },
            },
            handler=lambda args: self._kernel_file_tool("run_tests", args),
        )

    def register_git_tools(self) -> None:
        """Register git tools from the kernel."""
        if not self.kernel:
            return
        self.register_tool(
            name="git_status",
            description="Get the git working tree status.",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to git repository", "default": "."},
                },
            },
            handler=lambda args: self._kernel_file_tool("git_status", args),
        )
        self.register_tool(
            name="git_diff",
            description="Get git diff of changes.",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to git repository", "default": "."},
                    "staged": {"type": "boolean", "description": "Show staged changes only", "default": False},
                },
            },
            handler=lambda args: self._kernel_file_tool("git_diff", args),
        )
