"""Autonomous agent loop implementation for intelligent tool-calling agents.

This module provides the AutonomousAgent class which implements a multi-turn
conversation loop where the LLM can iteratively invoke tools, observe results,
reason, and decide on the next action.
"""

import concurrent.futures
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
    file_operations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "done": self.done,
            "terminal_tool": self.terminal_tool,
            "metadata": self.metadata,
            "tool_calls_made": self.tool_calls_made,
            "rounds_used": self.rounds_used,
            "file_operations": self.file_operations,
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

    # Read-only tools safe for parallel execution
    READ_ONLY_TOOLS = {"read_file", "list_directory", "search_files", "check_syntax",
                       "git_status", "git_diff", "inspect_file", "check_html_structure",
                       "check_code_quality", "check_cross_file_consistency",
                       "check_requirements_coverage", "web_search", "web_fetch",
                       "browser_open_page", "browser_screenshot", "browser_check_elements",
                       "browser_check_console", "browser_test_responsive",
                       "browser_get_page_info"}

    # Context window management
    MAX_MESSAGES = 50
    MAX_TOOL_RESULT_CHARS = 20000
    MAX_COMMAND_OUTPUT_CHARS = 50000  # Larger limit for command output (builds, tests)

    # Urgency message injected when agent is nearing max_rounds without submitting
    URGENCY_MESSAGE = (
        "URGENT: You are running out of rounds. You MUST call your submit/terminal tool NOW. "
        "Do NOT make any more tool calls. Submit your current result immediately."
    )

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        kernel=None,
        max_rounds: int = 40,
        urgency_threshold: float = 0.6,
        on_progress: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.kernel = kernel
        self.max_rounds = max_rounds
        self.urgency_threshold = urgency_threshold
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._logger = logging.getLogger(f"AutonomousAgent.{agent_name}")
        self._on_progress = on_progress  # Optional progress callback

        # Track file operations made during the loop for artifact extraction
        self._file_operations: list[dict[str, Any]] = []
        # Track files that have been read in this loop (read-before-write safety)
        self._files_read: set[str] = set()

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

    def _format_tool_result(self, tool_name: str, result: ToolResult) -> str:
        """Format and truncate a tool result for inclusion in messages.

        Uses a larger limit for command output (run_command, run_tests, verify_build)
        and applies smart truncation that preserves the most important parts.
        """
        result_dict = result.to_dict()

        # Determine the character limit based on tool type
        is_command_tool = tool_name in ("run_command", "run_tests", "verify_build",
                                         "execute_command", "execute_python")
        max_chars = self.MAX_COMMAND_OUTPUT_CHARS if is_command_tool else self.MAX_TOOL_RESULT_CHARS

        # For command tools, restructure the output for better LLM readability
        if is_command_tool and result.success and isinstance(result.result, dict):
            result_dict = self._format_command_result(tool_name, result.result)

        result_str = json.dumps(result_dict, ensure_ascii=False)

        if len(result_str) > max_chars:
            self._logger.warning(
                "[%s] Truncating tool result for '%s' from %d to %d chars",
                self.agent_name, tool_name, len(result_str), max_chars,
            )
            # Smart truncation: preserve structure and key information
            result_str = self._smart_truncate_result(result_str, max_chars, is_command_tool)

        return result_str

    def _format_command_result(self, tool_name: str, cmd_result: dict[str, Any]) -> dict[str, Any]:
        """Restructure command output for maximum LLM readability.

        Puts the most important information first: exit code, then errors, then output.
        Adds clear visual markers for success/failure.
        """
        formatted: dict[str, Any] = {"success": True}

        returncode = cmd_result.get("returncode", cmd_result.get("ok", -1))
        if isinstance(returncode, bool):
            returncode = 0 if returncode else 1

        stdout = cmd_result.get("stdout", "")
        stderr = cmd_result.get("stderr", "")
        ok = cmd_result.get("ok", True)

        # Determine success/failure
        if returncode != 0 or not ok:
            formatted["success"] = False
            formatted["❌ COMMAND FAILED"] = f"exit code {returncode}"
            # Put stderr FIRST when there's an error — it's more important
            if stderr:
                formatted["stderr"] = stderr
            if stdout:
                formatted["stdout"] = stdout
            # Add error classification
            error_type = self._classify_command_error(stderr or stdout or "", returncode)
            if error_type:
                formatted["error_type"] = error_type
            # Add actionable suggestion
            suggestion = self._suggest_fix(stderr or stdout or "", returncode)
            if suggestion:
                formatted["suggestion"] = suggestion
        else:
            formatted["✅ COMMAND SUCCEEDED"] = f"exit code {returncode}"
            if stdout:
                formatted["stdout"] = stdout
            if stderr:
                formatted["stderr"] = stderr

        # Preserve any additional fields from the original result
        for key in ("ok", "action", "path", "matches", "count", "items", "valid",
                     "error_type", "error_summary"):
            if key in cmd_result and key not in formatted:
                formatted[key] = cmd_result[key]

        return formatted

    def _classify_command_error(self, output: str, returncode: int) -> str:
        """Classify the type of command error from output and return code."""
        output_lower = output.lower()
        if "command not found" in output_lower or "is not recognized" in output_lower:
            return "command_not_found"
        if "permission denied" in output_lower or "eacces" in output_lower:
            return "permission_denied"
        if "timed out" in output_lower or "timeout" in output_lower:
            return "timeout"
        if any(word in output_lower for word in ("compilation error", "syntaxerror", "syntax error",
                                                    "build failed", "compilation failed")):
            return "build_error"
        if any(word in output_lower for word in ("test failed", "test failure", "assertionerror",
                                                    "assertion error", "tests failed")):
            return "test_failure"
        if any(word in output_lower for word in ("module not found", "importerror",
                                                    "no module named", "cannot find module")):
            return "dependency_error"
        if any(word in output_lower for word in ("runtime error", "exception", "traceback")):
            return "runtime_error"
        return "unknown_error" if returncode != 0 else ""

    def _suggest_fix(self, output: str, returncode: int) -> str:
        """Suggest a fix based on the error output."""
        output_lower = output.lower()
        if "command not found" in output_lower or "is not recognized" in output_lower:
            return "The command was not found. Check that the required tool is installed and in your PATH."
        if "permission denied" in output_lower:
            return "Permission denied. Try running with appropriate permissions or check file ownership."
        if "eacces" in output_lower or "access denied" in output_lower:
            return "Access denied. Check file/directory permissions."
        if "module not found" in output_lower or "no module named" in output_lower:
            return "A dependency is missing. Try running 'npm install' or 'pip install' first."
        if "cannot find module" in output_lower:
            return "A Node.js module is missing. Try running 'npm install' first."
        if "port" in output_lower and ("in use" in output_lower or "already" in output_lower):
            return "A port is already in use. Try a different port or kill the existing process."
        if returncode == 1:
            return "The command exited with an error. Check the stderr output above for details."
        if returncode == 2:
            return "The command exited with a usage error. Check the command syntax and arguments."
        return ""

    def _smart_truncate_result(self, result_str: str, max_chars: int, is_command: bool) -> str:
        """Smart truncation that preserves the most important parts of a result.

        For command results: keeps first and last portions, preserving exit code info.
        For other results: keeps the beginning and adds a truncation notice.
        """
        if len(result_str) <= max_chars:
            return result_str

        if is_command:
            # For command output, try to keep the beginning (exit code, first errors)
            # and the end (final summary, last errors)
            head_size = int(max_chars * 0.6)
            tail_size = int(max_chars * 0.35)
            head = result_str[:head_size]
            tail = result_str[-tail_size:]
            omitted = len(result_str) - head_size - tail_size
            return f"{head}\n...[{omitted} chars omitted — {len(result_str)} chars total]...\n{tail}"
        else:
            # For other results, keep the beginning and truncate
            head = result_str[:max_chars - 100]
            return f"{head}...[truncated — {len(result_str)} chars total]"

    def _trim_messages(self, messages: list[dict[str, Any]]) -> None:
        """Trim message history when it grows too large.

        Keeps the system prompt, the first user message, and the most recent
        messages. Summarizes the dropped middle section.
        """
        if len(messages) <= 5:
            return

        # Always keep: system prompt (0), first user message (1), and last ~10 messages
        keep_recent = 10
        system_msg = messages[0]
        first_user_msg = messages[1]
        recent_msgs = messages[-keep_recent:]

        # Count how many tool calls were in the dropped section
        dropped = messages[2:-keep_recent]
        tool_names_in_dropped = []
        for m in dropped:
            tn = m.get("tool_name")
            if tn:
                tool_names_in_dropped.append(tn)

        summary_parts = [f"Zwischendurch wurden {len(dropped)} Nachrichten ausgetauscht."]
        if tool_names_in_dropped:
            from collections import Counter
            counts = Counter(tool_names_in_dropped)
            summary_parts.append("Tools genutzt: " + ", ".join(f"{n}({c}x)" for n, c in counts.most_common(5)))

        summary = " ".join(summary_parts)

        messages.clear()
        messages.append(system_msg)
        messages.append(first_user_msg)
        messages.append({"role": "system", "content": f"[Kontext-Zusammenfassung: {summary}]"})
        messages.extend(recent_msgs)

        self._logger.info("[%s] Trimmed message history from %d to %d entries",
                          self.agent_name, len(dropped) + keep_recent + 2, len(messages))

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

        # Reset file operation tracking
        self._file_operations = []
        self._files_read = set()

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
                # Calculate adaptive timeout based on model and context
                chat_timeout = 300  # sensible default
                if hasattr(self.kernel, 'timeout_manager') and self.kernel.timeout_manager:
                    model_name = getattr(self.kernel, 'config', None)
                    model_name = model_name.get("ollama.model") if model_name and hasattr(model_name, 'get') else None
                    chat_timeout = self.kernel.timeout_manager.calculate_timeout(
                        model_name=model_name,
                        estimated_tokens=len(messages) * 100,  # rough estimate
                    )

                resp = self.kernel.ollama.chat(
                    messages=messages,
                    tools=tools,
                    stream=False,
                    timeout_s=chat_timeout,
                )
            except Exception as e:
                self._logger.exception("[%s] LLM call failed", self.agent_name)
                return AgentLoopResult(
                    content=f"Error: LLM call failed: {e}",
                    done=False,
                    rounds_used=round_num,
                    tool_calls_made=total_tool_calls,
                    file_operations=list(self._file_operations),
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
                    file_operations=list(self._file_operations),
                )

        # Execute each tool call
            # Separate read-only vs write tools for parallel dispatch
            read_only_calls = []
            write_calls = []
            for call in tool_calls:
                name, args = self._parse_tool_call(call)
                if name in self.READ_ONLY_TOOLS:
                    read_only_calls.append((name, args, call))
                else:
                    write_calls.append((name, args, call))

            # Execute read-only tools in parallel
            if read_only_calls:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(read_only_calls), 4)) as executor:
                    futures = {}
                    for name, args, _ in read_only_calls:
                        future = executor.submit(self.execute_tool, name, args)
                        futures[future] = (name, args)

                    for future in concurrent.futures.as_completed(futures):
                        name, args = futures[future]
                        total_tool_calls += 1
                        self._logger.info("[%s] Tool call: %s(args=%s)", self.agent_name, name, args)
                        try:
                            result = future.result()
                        except Exception as e:
                            result = ToolResult(success=False, error=str(e))
                        result_str = self._format_tool_result(name, result)
                        messages.append({"role": "tool", "tool_name": name, "content": result_str})

                        # Track files that have been read (read-before-write safety)
                        if name == "read_file" and result.success:
                            file_path = args.get("path", "")
                            if file_path:
                                self._files_read.add(file_path)

                        # Progress callback
                        if self._on_progress:
                            self._on_progress({
                                "round": round_num + 1,
                                "tool": name,
                                "success": result.success,
                                "result_summary": result_str[:200] if result_str else "",
                            })

            # Execute write tools sequentially
            for name, args, _ in write_calls:
                total_tool_calls += 1

                # Read-before-write safety: enforce reading before editing
                if name == "update_file":
                    file_path = args.get("path", "")
                    if file_path and file_path not in self._files_read:
                        self._logger.warning(
                            "[%s] ⚠️ update_file called on '%s' without reading it first! "
                            "Blocking the edit — read the file first to avoid unintended overwrites.",
                            self.agent_name, file_path,
                        )
                        # Return an error instead of proceeding with the edit
                        result_str = json.dumps({
                            "ok": False,
                            "error": f"Cannot update '{file_path}': you must read this file first with read_file before editing it. "
                                     f"This prevents accidental overwrites. Call read_file on this file first, then retry the update.",
                            "path": file_path,
                        })
                        messages.append({"role": "tool", "tool_name": name, "content": result_str})
                        continue

                self._logger.info("[%s] Tool call: %s(args=%s)", self.agent_name, name, args)
                result = self.execute_tool(name, args)
                result_dict = result.to_dict()
                result_str = self._format_tool_result(name, result)

                # Track file operations for artifact extraction
                if name in ("create_file", "update_file", "delete_file", "create_document", "create_report"):
                    file_path = args.get("path", args.get("filename", ""))
                    if file_path:
                        self._file_operations.append({
                            "action": name,
                            "path": file_path,
                            "size_bytes": 0,  # filled below if available
                        })
                        # Try to extract size from the result
                        if result.success and isinstance(result.result, dict):
                            size = result.result.get("size_bytes", result.result.get("size", 0))
                            self._file_operations[-1]["size_bytes"] = size

                if self._is_terminal_tool(name):
                    self._logger.info("[%s] Terminal tool '%s' called after %d rounds", self.agent_name, name, round_num + 1)
                    # Progress callback for terminal tool
                    if self._on_progress:
                        self._on_progress({
                            "round": round_num + 1,
                            "tool": name,
                            "success": result.success,
                            "terminal": True,
                            "result_summary": result_str[:200] if result_str else "",
                        })
                    return AgentLoopResult(
                        content=result_str,
                        done=True,
                        terminal_tool=name,
                        rounds_used=round_num + 1,
                        tool_calls_made=total_tool_calls,
                        metadata={"terminal_result": result_dict},
                        file_operations=list(self._file_operations),
                    )

                messages.append({"role": "tool", "tool_name": name, "content": result_str})

                # Progress callback for write tools
                if self._on_progress:
                    self._on_progress({
                        "round": round_num + 1,
                        "tool": name,
                        "success": result.success,
                        "result_summary": result_str[:200] if result_str else "",
                    })

            # Inject urgency message once when nearing max rounds without submitting
            urgency_round = int(max_rounds * self.urgency_threshold)
            if round_num + 1 == urgency_round:
                self._logger.warning("[%s] Injecting urgency message at round %d (threshold=%d)",
                                     self.agent_name, round_num + 1, urgency_round)
                messages.append({"role": "user", "content": self.URGENCY_MESSAGE})

            # Inject final urgency message at 2 rounds before the end
            final_round = max_rounds - 1
            if round_num + 1 == final_round and max_rounds > 3:
                self._logger.warning("[%s] Injecting FINAL urgency message at round %d",
                                     self.agent_name, round_num + 1)
                messages.append({"role": "user", "content": (
                    "CRITICAL: This is your LAST chance. Call your submit/terminal tool IMMEDIATELY. "
                    "You have 1 round left. Do NOT make any more tool calls. Submit NOW."
                )})

            # Context window management: trim if messages grow too large
            if len(messages) > self.MAX_MESSAGES:
                self._trim_messages(messages)

        # Max rounds exceeded
        self._logger.warning("[%s] Loop exceeded max rounds (%d)", self.agent_name, max_rounds)
        return AgentLoopResult(
            content=f"Autonomous loop exceeded maximum rounds ({max_rounds})",
            done=False,
            rounds_used=max_rounds,
            tool_calls_made=total_tool_calls,
            file_operations=list(self._file_operations),
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
            description="Edit an existing file. Three modes: (1) Find & Replace: provide 'old_content' and 'new_content' to surgically replace a specific section — ALWAYS read the file first to get exact text. (2) Append: provide 'content' with 'append=true' to add content to the end of a file. (3) Full Overwrite: provide 'content' only — replaces the ENTIRE file. Use ONLY for complete rewrites. ⚠️ WARNING: You MUST call read_file on a file BEFORE editing it with update_file. Editing a file you haven't read risks destroying existing content. The system tracks which files you've read and will warn you if you try to edit an unread file.",
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
        """Delegate a file tool call to the kernel.

        The kernel's _dispatch_tool returns a JSON string. We parse it once
        and return the dict directly so that _format_tool_result can properly
        format it for the LLM. This avoids double-encoding.
        """
        result_str = self.kernel._dispatch_tool(tool_name, args)
        try:
            parsed = json.loads(result_str)
            # Return the parsed dict directly — it will be wrapped in ToolResult
            # by execute_tool, then properly formatted by _format_tool_result.
            # No double-encoding: the dict flows through naturally.
            return parsed
        except json.JSONDecodeError:
            # If the kernel returned non-JSON (shouldn't happen normally),
            # wrap it in a simple dict
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
            description=(
                "Run a shell command in the workspace. Use this to build projects, run tests, "
                "install dependencies, or execute any shell command. IMPORTANT: Always check the "
                "returncode field in the result — 0 means success, any other value means failure. "
                "When a command fails, read the stderr field for error details. "
                "For build commands (npm run build, ng build, etc.), use timeout=120 or higher."
            ),
            schema={
                "type": "object",
                "required": ["command"],
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds (use 120+ for builds)", "default": 120},
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

    def register_verify_build_tool(self) -> None:
        """Register the verify_build tool from the kernel.

        This tool auto-detects the project type and runs the appropriate
        build command, returning structured results with error classification.
        """
        if not self.kernel:
            return
        self.register_tool(
            name="verify_build",
            description=(
                "Detect the project type and run the appropriate build command. "
                "Automatically detects Angular, React, Vue, Next.js, Vite, Node.js, Python, "
                "and other project types. Returns structured results with success/failure, "
                "error details, error type classification, and fix suggestions. "
                "IMPORTANT: Always call this BEFORE submitting your result to verify the build succeeds."
            ),
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the project root (default: '.')", "default": "."},
                    "build_command": {"type": "string", "description": "Optional override build command (e.g., 'npm run build:prod'). If not provided, auto-detected from project config."},
                    "timeout": {"type": "integer", "description": "Timeout in seconds for the build (default: 180)", "default": 180},
                },
            },
            handler=lambda args: self._kernel_file_tool("verify_build", args),
        )
