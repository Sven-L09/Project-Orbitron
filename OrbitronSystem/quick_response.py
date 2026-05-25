"""Quick Response Module — Handles simple requests without the full agent pipeline.

The QuickResponder uses a single LLM call to classify incoming requests:
- "simple" → answered directly (file listing, file content, project structure, etc.)
- "complex" → forwarded to the full Orchestrator pipeline

This avoids spinning up Planner → Executor → Tester for trivial questions
like "welche dateien sind im ordner xy" or "zeige mir den inhalt von datei.py".
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Ensure project root is on sys.path before importing OrbitronUtils
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from OrbitronUtils.dates import months_de, format_date_de, format_date_iso

logger = logging.getLogger("QuickResponder")


class QuickResponder:
    """Classifies and handles simple requests without the full agent pipeline.

    Uses a single LLM call to decide if a request is simple enough to answer
    directly. If so, the LLM also provides the answer using available tools
    (file listing, file reading, etc.). If not, returns None and the request
    falls through to the normal Orchestrator workflow.
    """

    def __init__(
        self,
        kernel,  # OrbitronKernel instance
        workspace_root: str | Path | None = None,
    ):
        self.kernel = kernel
        self.workspace_root = Path(workspace_root) if workspace_root else Path.cwd()

        # Build the classification + response prompt
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        """Build the system prompt for the QuickResponder LLM call."""
        # Inject current date so the LLM knows the correct date
        current_date_de = format_date_de()
        current_date_iso = format_date_iso()

        return f"""You are Orbitron's Quick Response system. Your job is to decide whether a user request is SIMPLE or COMPLEX.

## CRITICAL: Current Date
Today's date is **{current_date_de}** ({current_date_iso}).
- ALWAYS use this date when answering date-related questions.
- NEVER guess or assume a different date.

## SIMPLE requests — you handle them directly:
- Listing files or directories (e.g., "welche dateien sind im ordner xy", "list files in xy", "zeige mir die dateien in xy")
- Reading file contents (e.g., "zeige mir den inhalt von datei.py", "was steht in datei.py", "show me the content of file.py")
- Showing project structure (e.g., "wie ist das projekt aufgebaut", "show me the project structure")
- Simple factual questions that don't require code changes (e.g., "was ist eine python list comprehension")
- Status queries (e.g., "welche tasks laufen", "system status")
- Simple lookups or searches that don't modify anything

## COMPLEX requests — must be forwarded to the full pipeline:
- Creating, modifying, or deleting files
- Building features, apps, or systems
- Refactoring or debugging code
- Multi-step tasks that require planning and execution
- Any task that involves writing code or making changes
- Tasks that require testing or validation
- **Calendar-related requests** (e.g., "welchen termin habe ich", "schaue in google calendar", "zeige meine termine", "was steht in meinem kalalender", "habe ich morgen einen termin") — these require the calendar tools which are only available in the Orchestrator
- **Any request that requires accessing external services** (calendar, email, web APIs) — the QuickResponder only has file tools, not calendar or external service tools
- **Follow-up questions** that reference previous conversations or tasks (e.g., "hast du das gemacht?", "ändere das", "schreibe das als dokument") — these need context from the full pipeline
- **Output/delivery requests** (e.g., "gebe mir das", "schick mir das dokument", "hier im chat ausgeben") — these require the Executor to produce and deliver content
- **Any request with pronouns referencing previous context** (e.g., "das", "die", "es" referring to something previously discussed) — these need the full pipeline to resolve references

## Your response format:
You MUST respond with valid JSON only. No markdown, no explanation, just JSON.

If the request is SIMPLE:
```json
{{
  "is_simple": true,
  "response": "Your direct answer to the user in German (the user's language). Be concise and helpful."
}}
```

If the request is COMPLEX:
```json
{{
  "is_simple": false,
  "reason": "Brief reason why this needs the full pipeline"
}}
```

## REPLY CONTEXT:
If the user message includes a "[Antwort auf Nachricht von ...]" section, this means the user is replying to a previous message. Use this context to understand what the user is referring to. For example:
- If the user says "schreibe das in einem docx" and the reply context contains an email draft, they want THAT email draft saved as a .docx file.
- If the user says "ändere das" and the reply context contains code, they want THAT code modified.

## IMPORTANT RULES:
1. When in doubt, classify as COMPLEX — it's better to over-process than to under-process
2. For file/directory questions, use the provided workspace tools to get REAL information, don't guess
3. Always respond in the user's language (German if they write in German)
4. Be concise — simple requests deserve simple answers
5. NEVER try to modify, create, or delete files — only read and list
6. If the user references something from the reply context (e.g., "das", "das hier", "diesen Text"), always include the full context from the reply when classifying — the request is about the referenced content, not about something else in the workspace
"""

    def try_quick_response(
        self,
        user_text: str,
        chat_id: int | None = None,
        username: str = "Sven",
        reply_context: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Try to handle a request with a quick response.

        Args:
            user_text: The user's message text
            chat_id: Optional chat ID for context
            username: Username for context
            reply_context: Context from the message being replied to (Telegram reply_to_message)

        Returns:
            If the request is simple: {"is_simple": True, "response": "..."}
            If the request is complex: None (falls through to full pipeline)
        """
        if not self.kernel:
            logger.debug("[QuickResponder] No kernel available, skipping")
            return None

        user_text_lower = user_text.lower()

        # Pre-check 1: Calendar-related requests must go to the Orchestrator
        # because the QuickResponder doesn't have calendar tools
        calendar_keywords = [
            "kalender", "calendar", "termin", "appointment", "event",
            "termin habe ich", "habe ich einen termin", "welchen termin",
            "meine termine", "steht im kalender", "schaue in google calendar",
            "google calendar", "upcoming events", "free busy", "freebusy",
            "termine für", "events for", "what's on my calendar",
            "was steht an", "was habe ich", "habe ich morgen",
        ]
        if any(kw in user_text_lower for kw in calendar_keywords):
            logger.info("[QuickResponder] Calendar-related request detected, forwarding to Orchestrator: %s", user_text[:80])
            return None  # Fall through to full pipeline

        # Pre-check 2: Follow-up questions with reply context must go to the Orchestrator
        # because they reference previous tasks/conversations the QuickResponder has no knowledge of.
        # Examples: "Hast du das bereits gemacht?", "Ändere das", "Schreibe das als Dokument"
        if reply_context:
            logger.info("[QuickResponder] Request with reply context detected, forwarding to Orchestrator: %s", user_text[:80])
            return None  # Fall through to full pipeline

        # Pre-check 3: Output/delivery/action requests must go to the Orchestrator
        # because they require executing actions the QuickResponder can't perform.
        # Examples: "Gebe die mir mal hier im chat aus", "Schick mir das Dokument"
        action_keywords = [
            "gebe mir", "gib mir", "schick mir", "schicke mir", "sende mir",
            "gebe die", "gib die", "schick die", "sende die",
            "gebe das", "gib das", "schick das", "sende das",
            "hier im chat", "im chat aus", "im chat ausgeben",
            "als datei", "als dokument", "als docx", "als pdf",
            "exportiere", "download", "herunterladen",
            "erstelle mir", "erzeuge mir", "generiere mir",
            "schreibe das in", "schreibe mir", "baue mir",
            "mache ein", "mach ein", "erstelle ein",
        ]
        if any(kw in user_text_lower for kw in action_keywords):
            logger.info("[QuickResponder] Action/output request detected, forwarding to Orchestrator: %s", user_text[:80])
            return None  # Fall through to full pipeline

        try:
            # Get workspace context for the LLM
            workspace_info = self._get_workspace_context()

            # Build the user message with workspace context and reply context
            user_message = (
                f"User request: {user_text}\n\n"
                f"Workspace root: {self.workspace_root}\n"
                f"{workspace_info}"
            )

            # Include reply context if available (from Telegram reply_to_message)
            if reply_context:
                user_message = f"{reply_context}\n\n{user_message}"

            # Single LLM call with tools for file operations
            messages = [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ]

            # Use the kernel's chat with tools enabled for file operations
            response = self.kernel.ollama.chat(
                messages=messages,
                tools=self._get_quick_tools(),
                stream=False,
                timeout_s=60,
                max_retries=1,
            )

            # Process tool calls if any
            msg = response.get("message", {})
            tool_calls = msg.get("tool_calls", [])

            # Handle tool calls — execute them and get the final response
            if tool_calls:
                messages.append(msg)
                for call in tool_calls:
                    tool_result = self._execute_tool_call(call)
                    messages.append({
                        "role": "tool",
                        "tool_name": self._extract_tool_name(call),
                        "content": tool_result,
                    })

                # Get final response after tool execution
                final_response = self.kernel.ollama.chat(
                    messages=messages,
                    tools=self._get_quick_tools(),
                    stream=False,
                    timeout_s=60,
                    max_retries=1,
                )
                final_content = str((final_response.get("message") or {}).get("content") or "")
            else:
                final_content = str(msg.get("content", ""))

            if not final_content:
                logger.debug("[QuickResponder] Empty response from LLM, falling through")
                return None

            # Parse the JSON response
            result = self._parse_llm_response(final_content)

            if result is None:
                logger.debug("[QuickResponder] Could not parse LLM response, falling through")
                return None

            if result.get("is_simple") is True:
                logger.info("[QuickResponder] Handled as simple request: %s", user_text[:80])
                return {
                    "is_simple": True,
                    "response": result.get("response", ""),
                    "task_type": "quick_response",
                }
            else:
                logger.info("[QuickResponder] Classified as complex: %s", result.get("reason", "unknown"))
                return None

        except Exception as e:
            logger.warning("[QuickResponder] Error during quick response: %s", e)
            return None

    def _get_workspace_context(self) -> str:
        """Get basic workspace context for the LLM."""
        try:
            # List top-level directories and files
            items = []
            for item in sorted(self.workspace_root.iterdir()):
                if item.name.startswith(".") and item.name != ".env":
                    continue
                if item.is_dir():
                    try:
                        sub_count = len(list(item.iterdir()))
                        items.append(f"  {item.name}/ ({sub_count} items)")
                    except PermissionError:
                        items.append(f"  {item.name}/ (no access)")
                else:
                    size = item.stat().st_size
                    items.append(f"  {item.name} ({size} bytes)")

            context = "Workspace contents (top level):\n" + "\n".join(items[:30])
            return context
        except Exception as e:
            return f"Workspace: {self.workspace_root} (error listing: {e})"

    def _get_quick_tools(self) -> list[dict[str, Any]]:
        """Get the tools available for quick responses (read-only operations only)."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List files and directories in a path within the workspace. Use this to answer questions about what files exist.",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path from workspace root (use '.' for root)"
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read the content of a file in the workspace. Use this to show file contents.",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Relative path to the file from workspace root"
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": "Search for files matching a pattern in the workspace.",
                    "parameters": {
                        "type": "object",
                        "required": ["pattern"],
                        "properties": {
                            "pattern": {
                                "type": "string",
                                "description": "Search pattern (filename or glob pattern)"
                            },
                            "path": {
                                "type": "string",
                                "description": "Directory to search in (relative to workspace root)",
                                "default": "."
                            },
                        },
                    },
                },
            },
        ]

    def _execute_tool_call(self, call: dict[str, Any]) -> str:
        """Execute a tool call from the LLM response."""
        tool_name = self._extract_tool_name(call)
        args = self._extract_tool_args(call)

        try:
            if tool_name == "list_directory":
                path = args.get("path", ".")
                full_path = self._resolve_path(path)
                if not full_path.exists() or not full_path.is_dir():
                    return json.dumps({"error": f"Directory not found: {path}"})

                entries = []
                for item in sorted(full_path.iterdir()):
                    if item.name.startswith(".") and item.name != ".env":
                        continue
                    if item.is_dir():
                        try:
                            sub_count = len(list(item.iterdir()))
                            entries.append(f"{item.name}/ ({sub_count} items)")
                        except PermissionError:
                            entries.append(f"{item.name}/")
                    else:
                        size = item.stat().st_size
                        entries.append(f"{item.name} ({size} bytes)")

                return json.dumps({"path": path, "entries": entries})

            elif tool_name == "read_file":
                path = args.get("path", "")
                full_path = self._resolve_path(path)
                if not full_path.exists() or not full_path.is_file():
                    return json.dumps({"error": f"File not found: {path}"})

                # Limit file size for quick responses
                size = full_path.stat().st_size
                if size > 50000:  # 50KB limit
                    content = full_path.read_text(encoding="utf-8", errors="replace")[:50000]
                    return json.dumps({
                        "path": path,
                        "content": content,
                        "truncated": True,
                        "total_size": size,
                    })

                content = full_path.read_text(encoding="utf-8", errors="replace")
                return json.dumps({"path": path, "content": content})

            elif tool_name == "search_files":
                pattern = args.get("pattern", "")
                search_path = args.get("path", ".")
                full_search_path = self._resolve_path(search_path)

                if not full_search_path.exists():
                    return json.dumps({"error": f"Path not found: {search_path}"})

                matches = []
                for item in full_search_path.rglob(pattern):
                    if item.name.startswith(".") and item.name != ".env":
                        continue
                    try:
                        rel = item.relative_to(self.workspace_root)
                        matches.append(str(rel))
                    except ValueError:
                        matches.append(str(item))
                    if len(matches) >= 50:
                        break

                return json.dumps({"pattern": pattern, "matches": matches})

            else:
                return json.dumps({"error": f"Unknown tool: {tool_name}"})

        except Exception as e:
            logger.warning("[QuickResponder] Tool execution error: %s", e)
            return json.dumps({"error": str(e)})

    def _resolve_path(self, path: str) -> Path:
        """Resolve a relative path against the workspace root."""
        p = Path(path)
        if p.is_absolute():
            return p.resolve()
        return (self.workspace_root / p).resolve()

    def _extract_tool_name(self, call: dict[str, Any]) -> str:
        """Extract tool name from a tool call."""
        if isinstance(call, dict):
            func = call.get("function", {})
            if isinstance(func, dict):
                return func.get("name", "")
        return ""

    def _extract_tool_args(self, call: dict[str, Any]) -> dict[str, Any]:
        """Extract tool arguments from a tool call."""
        if isinstance(call, dict):
            func = call.get("function", {})
            if isinstance(func, dict):
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        return json.loads(args)
                    except json.JSONDecodeError:
                        return {}
                if isinstance(args, dict):
                    return args
        return {}

    def _parse_llm_response(self, content: str) -> Optional[dict[str, Any]]:
        """Parse the LLM response as JSON.

        The LLM should return JSON, but sometimes wraps it in markdown
        code blocks or adds extra text. This method handles those cases.
        """
        content = content.strip()

        # Try direct JSON parse
        try:
            result = json.loads(content)
            if isinstance(result, dict) and "is_simple" in result:
                return result
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code block
        import re
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if json_match:
            try:
                result = json.loads(json_match.group(1).strip())
                if isinstance(result, dict) and "is_simple" in result:
                    return result
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in the text
        brace_match = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if brace_match:
            try:
                result = json.loads(brace_match.group(0))
                if isinstance(result, dict) and "is_simple" in result:
                    return result
            except json.JSONDecodeError:
                pass

        return None