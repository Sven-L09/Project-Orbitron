"""Main kernel module for Orbitron."""

import importlib.util
import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("SkillRegistry")

try:
    # Package import (recommended): python -m OrbitronKernel.main / OrbitronSystem/main.py
    from .OllamaConnector import OllamaConnector
    from .config import Config
    from .file_operations import FileOperations
    from .timeout_manager import TimeoutManager
except ImportError:
    # Script import fallback (legacy): run from within OrbitronKernel directory
    from OllamaConnector import OllamaConnector
    from config import Config
    from file_operations import FileOperations
    from timeout_manager import TimeoutManager


class AgentSkill:
    """Base class for agent-specific skills.
    
    Agents can extend this class to provide their own tools and capabilities
    that will be registered with the kernel.
    """
    
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._tools: list[dict[str, Any]] = []
        self._handlers: dict[str, callable] = {}
    
    def register_tool(self, name: str, schema: dict[str, Any], handler: callable) -> None:
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
    
    def get_handlers(self) -> dict[str, callable]:
        """Get all tool handlers for this skill."""
        return self._handlers
    
    def handle_tool(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute a tool handler by name."""
        if tool_name not in self._handlers:
            return json.dumps({"ok": False, "error": f"Unknown tool: {tool_name}"})
        try:
            result = self._handlers[tool_name](args)
            return json.dumps({"ok": True, "result": result}) if not isinstance(result, str) else result
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})


class SkillRegistry:
    """Registry for managing agent skills and their tools."""
    
    def __init__(self):
        self._skills: dict[str, AgentSkill] = {}
        self._all_tools: list[dict[str, Any]] = []
        self._all_handlers: dict[str, callable] = {}
    
    def register_skill(self, skill: AgentSkill) -> None:
        """Register an agent skill and its tools."""
        self._skills[skill.name] = skill
        
        # Add tools to the combined list
        for tool in skill.get_tools():
            self._all_tools.append(tool)
        
        # Add handlers to the combined dict
        for name, handler in skill.get_handlers().items():
            self._all_handlers[name] = handler
        
        logger.info("[SkillRegistry] Registered skill: %s with %d tools", skill.name, len(skill.get_tools()))
    
    def unregister_skill(self, skill_name: str) -> None:
        """Unregister a skill and remove its tools."""
        if skill_name not in self._skills:
            return
        
        skill = self._skills[skill_name]
        
        # Remove tools
        tool_names = {t["function"]["name"] for t in skill.get_tools()}
        self._all_tools = [t for t in self._all_tools if t["function"]["name"] not in tool_names]
        
        # Remove handlers
        for name in tool_names:
            self._all_handlers.pop(name, None)
        
        del self._skills[skill_name]
        logger.info("[SkillRegistry] Unregistered skill: %s", skill_name)
    
    def get_tools(self) -> list[dict[str, Any]]:
        """Get all registered tools."""
        return self._all_tools
    
    def get_handler(self, tool_name: str) -> Optional[callable]:
        """Get a tool handler by name."""
        return self._all_handlers.get(tool_name)
    
    def has_skill(self, skill_name: str) -> bool:
        """Check if a skill is registered."""
        return skill_name in self._skills
    
    def get_skill(self, skill_name: str) -> AgentSkill | None:
        """Get a registered skill by name."""
        return self._skills.get(skill_name)
    
    def list_skills(self) -> list[str]:
        """List all registered skill names."""
        return list(self._skills.keys())


class OrbitronKernel:
    """Main kernel class for Orbitron AI assistant."""
    
    def __init__(self, config_path: str | None = None):
        """Initialize the kernel."""
        self._load_dotenv()
        self.config = Config(config_path)
        self.file_ops = FileOperations(self.config.get("kernel.workspace"))
        self.ollama = OllamaConnector(
            base_url=self.config.get("ollama.base_url"),
            api_key=self.config.get("ollama.api_key"),
            model=self.config.get("ollama.model")
        )
        
        # Initialize skill registry
        self.skill_registry = SkillRegistry()
        
        # Load built-in tools and any agent skills
        self._base_tools = self._build_tools_schema()
        self._refresh_tools()
        
        sessions_dir = self.config.get("kernel.sessions_dir") or str(Path.home() / ".orbitron" / "sessions")
        self._sessions = SessionManager(sessions_dir, max_messages=40)

        # Initialize timeout manager for adaptive timeouts
        profiles_dir = self.config.get("kernel.profiles_dir") or str(Path.home() / ".orbitron" / "profiles")
        self.timeout_manager = TimeoutManager(profiles_dir=profiles_dir)

    def _load_dotenv(self) -> None:
        """Minimal .env loader (key=value per line) without external deps.

        Loads from the project root (parent of OrbitronKernel) and from the
        current working directory, if a `.env` file exists.
        Existing environment variables are not overwritten.
        """
        candidate_paths: list[Path] = []
        try:
            candidate_paths.append(Path(__file__).resolve().parents[1] / ".env")
        except Exception:
            pass
        candidate_paths.append(Path.cwd() / ".env")

        for env_path in candidate_paths:
            if not env_path.exists() or not env_path.is_file():
                continue
            try:
                for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if not key:
                        continue
                    os.environ.setdefault(key, value)
            except Exception:
                continue
    
    def _refresh_tools(self) -> None:
        """Refresh the combined tools list from base tools and registered skills."""
        self._tools = self._base_tools + self.skill_registry.get_tools()
    
    def register_skill(self, skill: AgentSkill) -> None:
        """Register an agent skill with the kernel."""
        self.skill_registry.register_skill(skill)
        self._refresh_tools()
    
    def unregister_skill(self, skill_name: str) -> None:
        """Unregister an agent skill from the kernel."""
        self.skill_registry.unregister_skill(skill_name)
        self._refresh_tools()
    
    def load_skill_from_file(self, skill_path: str) -> AgentSkill | None:
        """Load a skill from a Python file.
        
        The file should define a 'create_skill()' function that returns an AgentSkill instance.
        """
        try:
            path = Path(skill_path)
            if not path.exists():
                logger.warning("[Kernel] Skill file not found: %s", skill_path)
                return None
            
            # Load the module
            spec = importlib.util.spec_from_file_location("skill_module", path)
            if spec is None or spec.loader is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # Look for create_skill function
            if hasattr(module, "create_skill"):
                skill = module.create_skill()
                if isinstance(skill, AgentSkill):
                    logger.info("[Kernel] Loaded skill from %s: %s", path.name, skill.name)
                    return skill
            
            logger.warning("[Kernel] No create_skill() found in %s", skill_path)
            return None
        except Exception as e:
            logger.error("[Kernel] Error loading skill from %s: %s", skill_path, e)
            return None
    
    def load_skills_from_directory(self, skills_dir: str) -> list[AgentSkill]:
        """Load all skills from a directory."""
        loaded = []
        path = Path(skills_dir)
        if not path.exists():
            logger.warning("[Kernel] Skills directory not found: %s", skills_dir)
            return loaded
        
        for skill_file in path.glob("*.py"):
            skill = self.load_skill_from_file(str(skill_file))
            if skill:
                loaded.append(skill)
        
        return loaded

    def generate_response(self, prompt: str) -> str:
        """Generate a response using Ollama, allowing tool calls."""
        return self.assist(prompt)

    def assist(self, prompt: str, *, max_rounds: int = 10) -> str:
        """Convenience wrapper: one user prompt -> agent loop -> final content."""
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are Orbitron, a coding kernel with access to tools for file operations. "
                    "When the user requests filesystem changes, use the tools. "
                    "All file paths MUST be relative to the workspace. "
                    "After completing tool calls, respond with a concise summary of what changed."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        return self.run_chat(messages, max_rounds=max_rounds)

    def run_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_rounds: int = 10,
        timeout_s: Optional[int] = None,
        track_performance: bool = True,
    ) -> str:
        """Run an agent loop on an existing message list.

        This is suitable for multi-turn chat (e.g., Telegram) where you want to
        keep `messages` around per user/chat id.

        Args:
            messages: Message history
            max_rounds: Maximum tool call rounds
            timeout_s: Optional timeout override (uses TimeoutManager if not provided)
            track_performance: Whether to track response time for model profiling
        """
        import time

        model_name = self.config.get("ollama.model", "unknown")
        start_time = time.time()

        try:
            for _ in range(max_rounds):
                chat_kwargs = {
                    "messages": messages,
                    "tools": self._tools,
                    "stream": False,
                    "think": None,
                }
                if timeout_s is not None:
                    chat_kwargs["timeout_s"] = timeout_s
                else:
                    # Use TimeoutManager for adaptive timeout
                    chat_kwargs["timeout_s"] = self.timeout_manager.calculate_timeout(
                        model_name=model_name,
                    )

                resp = self.ollama.chat(**chat_kwargs)
                msg = resp.get("message") or {}
                if isinstance(msg, dict):
                    messages.append(msg)

                tool_calls = (msg.get("tool_calls") or []) if isinstance(msg, dict) else []
                if tool_calls:
                    for call in tool_calls:
                        tool_name, tool_args = self._extract_tool_call(call)
                        result = self._dispatch_tool(tool_name, tool_args)
                        messages.append({"role": "tool", "tool_name": tool_name, "content": result})
                    continue

                response_content = str(msg.get("content") or "")

                # Track performance
                if track_performance:
                    duration = time.time() - start_time
                    self.timeout_manager.update_profile(model_name, duration)

                return response_content

            return "Error: tool loop exceeded max rounds"

        except Exception as e:
            # Track failed execution
            if track_performance:
                duration = time.time() - start_time
                self.timeout_manager.update_profile(model_name, duration, was_successful=False)
            raise

    def _build_tools_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_file",
                    "description": "Create a new file in the workspace.",
                    "parameters": {
                        "type": "object",
                        "required": ["path", "content"],
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path"},
                            "content": {"type": "string", "description": "File contents"},
                            "overwrite": {"type": "boolean", "description": "Overwrite if exists", "default": False},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "update_file",
                    "description": "Edit an existing file. Three modes: (1) Find & Replace: provide 'old_content' and 'new_content' to surgically replace a specific section — always read the file first to get exact text. (2) Append: provide 'content' with 'append=true' to add content to the end of a file. (3) Full Overwrite: provide 'content' only — replaces the ENTIRE file. Use ONLY for complete rewrites. IMPORTANT: For editing existing files, prefer Find & Replace or Append to avoid accidentally deleting existing content.",
                    "parameters": {
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
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_file",
                    "description": "Delete a file in the workspace.",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path"},
                            "missing_ok": {"type": "boolean", "description": "Do not error if missing", "default": False},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file from the workspace.",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_directory",
                    "description": "List a directory in the workspace.",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string", "description": "Relative directory path"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_files",
                    "description": "Search for files or content matching a pattern in the workspace.",
                    "parameters": {
                        "type": "object",
                        "required": ["pattern"],
                        "properties": {
                            "pattern": {"type": "string", "description": "Search pattern or regex to match"},
                            "path": {"type": "string", "description": "Directory to search in (relative to workspace)", "default": "."},
                            "file_extension": {"type": "string", "description": "Optional file extension filter (e.g. '.py')"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_command",
                    "description": "Run a shell command in the workspace. Use with caution.",
                    "parameters": {
                        "type": "object",
                        "required": ["command"],
                        "properties": {
                            "command": {"type": "string", "description": "Shell command to execute"},
                            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
                            "cwd": {"type": "string", "description": "Working directory (relative to workspace)", "default": "."},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "check_syntax",
                    "description": "Check the syntax of a code file.",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path"},
                            "language": {"type": "string", "description": "Programming language (e.g. python, javascript)", "default": "python"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_tests",
                    "description": "Run tests for a module or project.",
                    "parameters": {
                        "type": "object",
                        "required": ["path"],
                        "properties": {
                            "path": {"type": "string", "description": "Relative path to test file or directory"},
                            "test_pattern": {"type": "string", "description": "Optional test pattern (e.g. 'test_*.py')"},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "git_status",
                    "description": "Get the git working tree status.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to git repository (relative to workspace)", "default": "."},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "git_diff",
                    "description": "Get git diff of changes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Path to git repository (relative to workspace)", "default": "."},
                            "staged": {"type": "boolean", "description": "Show staged changes only", "default": False},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for information. Returns a list of results with titles, URLs, and content snippets. Useful for looking up documentation, APIs, best practices, or current information.",
                    "parameters": {
                        "type": "object",
                        "required": ["query"],
                        "properties": {
                            "query": {"type": "string", "description": "The search query string"},
                            "max_results": {"type": "integer", "description": "Maximum number of results to return (1-10, default 5)", "default": 5},
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Fetch and read the content of a web page by URL. Returns the page title, content, and links. Useful for reading documentation, API references, or any web page.",
                    "parameters": {
                        "type": "object",
                        "required": ["url"],
                        "properties": {
                            "url": {"type": "string", "description": "The URL of the web page to fetch"},
                        },
                    },
                },
            },
        ]

    def get_session(self, chat_id: int) -> list[dict[str, Any]]:
        """Get or create a session for a chat_id."""
        return self._sessions.get(chat_id)

    def add_message_to_session(self, chat_id: int, message: dict[str, Any]) -> None:
        """Add a message to an existing session."""
        self._sessions.add_message(chat_id, message)

    def save_session(self, chat_id: int) -> None:
        """Persist a session to disk."""
        self._sessions.save(chat_id)

    def clear_session(self, chat_id: int) -> None:
        """Clear a session (start fresh)."""
        self._sessions.clear(chat_id)

    def process_command(self, command: str, args: list[str] | None = None) -> str:
        """Process a kernel command."""
        args = args or []

        if command == "help":
            return self._help()
        elif command == "read":
            return self._read_file(args)
        elif command == "write":
            return self._write_file(args)
        elif command == "delete":
            return self._delete_file(args)
        elif command == "create":
            return self._create_file(args)
        elif command == "list":
            return self._list_directory(args)
        elif command == "mkdir":
            return self._mkdir(args)
        elif command == "rmdir":
            return self._rmdir(args)
        else:
            return f"Unknown command: {command}"

    def _extract_tool_call(self, call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Extract tool name and args from Ollama tool_calls element."""
        # Expected shape (docs): {type:'function', function:{name:'...', arguments:{...}}}
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

    def _dispatch_tool(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        """Run a tool call and return string content for the tool result message."""
        # First check skill registry for agent-specific tools
        skill_handler = self.skill_registry.get_handler(tool_name)
        if skill_handler:
            try:
                result = skill_handler(tool_args)
                return json.dumps({"ok": True, "result": result}) if not isinstance(result, str) else result
            except Exception as e:
                return json.dumps({"ok": False, "error": str(e)})

        # Then check built-in tools
        try:
            if tool_name == "create_file":
                return self._tool_create_file(tool_args)
            if tool_name == "update_file":
                return self._tool_update_file(tool_args)
            if tool_name == "delete_file":
                return self._tool_delete_file(tool_args)
            if tool_name == "read_file":
                return self._tool_read_file(tool_args)
            if tool_name == "list_directory":
                return self._tool_list_directory(tool_args)
            if tool_name == "search_files":
                return self._tool_search_files(tool_args)
            if tool_name == "run_command":
                return self._tool_run_command(tool_args)
            if tool_name == "check_syntax":
                return self._tool_check_syntax(tool_args)
            if tool_name == "run_tests":
                return self._tool_run_tests(tool_args)
            if tool_name == "git_status":
                return self._tool_git_status(tool_args)
            if tool_name == "git_diff":
                return self._tool_git_diff(tool_args)
            if tool_name == "web_search":
                return self._tool_web_search(tool_args)
            if tool_name == "web_fetch":
                return self._tool_web_fetch(tool_args)
            return json.dumps({"ok": False, "error": f"Unknown tool: {tool_name}"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _require_rel_path(self, path: Any) -> str:
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        # FileOperations rejects absolute + escaping, but we validate early for clearer tool feedback.
        if path.startswith("/") or path.startswith("\\") or ":" in path:
            raise ValueError("path must be relative to workspace")
        if ".." in path.replace("\\", "/").split("/"):
            raise ValueError("path must not contain '..'")
        return path

    def _tool_create_file(self, args: dict[str, Any]) -> str:
        path = self._require_rel_path(args.get("path"))
        content = args.get("content")
        overwrite = bool(args.get("overwrite", False))
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        if self.file_ops.file_exists(path) and not overwrite:
            return json.dumps({"ok": False, "error": "File already exists", "path": path})
        self.file_ops.write_file(path, content)
        return json.dumps({"ok": True, "action": "create_file", "path": path})

    def _tool_update_file(self, args: dict[str, Any]) -> str:
        path = self._require_rel_path(args.get("path"))
        if not self.file_ops.file_exists(path):
            return json.dumps({"ok": False, "error": "File does not exist", "path": path})

        old_content = args.get("old_content")
        new_content = args.get("new_content")
        append = bool(args.get("append", False))
        content = args.get("content")

        # Mode: Find & Replace — surgically replace a specific section
        if old_content is not None:
            if not isinstance(old_content, str):
                raise ValueError("old_content must be a string")
            if new_content is None:
                new_content = ""
            file_content = self.file_ops.read_file(path)
            if old_content not in file_content:
                preview = old_content[:200] + "..." if len(old_content) > 200 else old_content
                return json.dumps({
                    "ok": False,
                    "error": "old_content not found in file",
                    "hint": "The exact text must match including whitespace. Use read_file first to verify the content.",
                    "path": path,
                    "old_content_preview": preview,
                    "file_size": len(file_content),
                })
            updated = file_content.replace(old_content, new_content)
            self.file_ops.write_file(path, updated)
            replacements = file_content.count(old_content)
            return json.dumps({
                "ok": True,
                "action": "update_file",
                "mode": "find_replace",
                "path": path,
                "replacements": replacements,
            })

        # Mode: Append — add content to the end of the file
        if append:
            if not isinstance(content, str):
                raise ValueError("content must be a string")
            self.file_ops.append_file(path, content)
            return json.dumps({"ok": True, "action": "update_file", "mode": "append", "path": path})

        # Mode: Full Overwrite — replace entire file (existing behavior)
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        self.file_ops.write_file(path, content)
        return json.dumps({"ok": True, "action": "update_file", "mode": "overwrite", "path": path})

    def _tool_delete_file(self, args: dict[str, Any]) -> str:
        path = self._require_rel_path(args.get("path"))
        missing_ok = bool(args.get("missing_ok", False))
        deleted = self.file_ops.delete_file(path)
        if not deleted and not missing_ok:
            return json.dumps({"ok": False, "error": "File not found", "path": path})
        return json.dumps({"ok": True, "action": "delete_file", "path": path, "deleted": deleted})

    def _tool_read_file(self, args: dict[str, Any]) -> str:
        path = self._require_rel_path(args.get("path"))
        content = self.file_ops.read_file(path)
        return json.dumps({"ok": True, "action": "read_file", "path": path, "content": content})

    def _tool_list_directory(self, args: dict[str, Any]) -> str:
        path = self._require_rel_path(args.get("path"))
        items = self.file_ops.list_directory(path)
        return json.dumps({"ok": True, "action": "list_directory", "path": path, "items": items})

    def _tool_search_files(self, args: dict[str, Any]) -> str:
        pattern = args.get("pattern", "")
        search_path = self._require_rel_path(args.get("path", "."))
        file_extension = args.get("file_extension")
        if not isinstance(pattern, str) or not pattern:
            return json.dumps({"ok": False, "error": "pattern must be a non-empty string"})
        try:
            target_dir = self.file_ops.workspace_root / search_path
            matches = []
            for root, dirs, files in os.walk(target_dir):
                # Skip hidden dirs and common non-source dirs
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"__pycache__", "node_modules", "venv", ".git"}]
                for filename in files:
                    if file_extension and not filename.endswith(file_extension):
                        continue
                    filepath = Path(root) / filename
                    try:
                        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        if re.search(pattern, content):
                            rel = str(filepath.relative_to(self.file_ops.workspace_root)).replace("\\", "/")
                            matches.append(rel)
                    except Exception:
                        continue
            return json.dumps({"ok": True, "action": "search_files", "pattern": pattern, "matches": matches, "count": len(matches)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _tool_run_command(self, args: dict[str, Any]) -> str:
        command = args.get("command", "")
        timeout = int(args.get("timeout", 30))
        cwd_rel = args.get("cwd", ".")
        if not isinstance(command, str) or not command:
            return json.dumps({"ok": False, "error": "command must be a non-empty string"})
        try:
            cwd = str(self.file_ops.workspace_root / cwd_rel)
            result = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            return json.dumps({
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "error": f"Command timed out after {timeout}s"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _tool_check_syntax(self, args: dict[str, Any]) -> str:
        path = self._require_rel_path(args.get("path"))
        language = args.get("language", "python")
        try:
            filepath = self.file_ops.workspace_root / path
            if not filepath.exists():
                return json.dumps({"ok": False, "error": "File does not exist", "path": path})
            if language.lower() == "python":
                import py_compile
                py_compile.compile(str(filepath), doraise=True)
                return json.dumps({"ok": True, "action": "check_syntax", "path": path, "language": language, "valid": True})
            else:
                return json.dumps({"ok": False, "error": f"Syntax checking not yet supported for {language}"})
        except py_compile.PyCompileError as e:
            return json.dumps({"ok": False, "action": "check_syntax", "path": path, "language": language, "valid": False, "error": str(e)})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _tool_run_tests(self, args: dict[str, Any]) -> str:
        path = self._require_rel_path(args.get("path"))
        test_pattern = args.get("test_pattern")
        try:
            target = self.file_ops.workspace_root / path
            if target.is_file():
                cmd = ["python", "-m", "pytest", str(target), "-v"]
            else:
                cmd = ["python", "-m", "pytest", str(target), "-v"]
            if test_pattern:
                cmd.append("-k")
                cmd.append(test_pattern)
            result = subprocess.run(
                cmd,
                cwd=str(self.file_ops.workspace_root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            return json.dumps({
                "ok": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
        except subprocess.TimeoutExpired:
            return json.dumps({"ok": False, "error": "Tests timed out after 120s"})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _tool_git_status(self, args: dict[str, Any]) -> str:
        path = args.get("path", ".")
        try:
            cwd = str(self.file_ops.workspace_root / path)
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return json.dumps({
                "ok": result.returncode == 0,
                "status": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
            })
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _tool_git_diff(self, args: dict[str, Any]) -> str:
        path = args.get("path", ".")
        staged = bool(args.get("staged", False))
        try:
            cwd = str(self.file_ops.workspace_root / path)
            cmd = ["git", "diff"]
            if staged:
                cmd.append("--staged")
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=30,
            )
            return json.dumps({
                "ok": result.returncode == 0,
                "diff": result.stdout,
                "error": result.stderr if result.returncode != 0 else None,
            })
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _tool_web_search(self, args: dict[str, Any]) -> str:
        """Search the web using the Ollama Web Search API."""
        query = args.get("query", "")
        max_results = int(args.get("max_results", 5))
        if not query:
            return json.dumps({"ok": False, "error": "No search query provided"})
        try:
            results = self.ollama.web_search(query=query, max_results=max_results)
            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "content": r.get("content", ""),
                })
            return json.dumps({"ok": True, "query": query, "results": formatted})
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _tool_web_fetch(self, args: dict[str, Any]) -> str:
        """Fetch a web page using the Ollama Web Fetch API."""
        url = args.get("url", "")
        if not url:
            return json.dumps({"ok": False, "error": "No URL provided"})
        try:
            data = self.ollama.web_fetch(url=url)
            return json.dumps({
                "ok": True,
                "title": data.get("title", ""),
                "content": data.get("content", ""),
                "links": data.get("links", []),
            })
        except Exception as e:
            return json.dumps({"ok": False, "error": str(e)})

    def _help(self) -> str:
        """Return help information."""
        return """Orbitron Kernel Commands:
  read <path>              - Read file content
  write <path> <content>   - Write content to file
  delete <path>            - Delete file
  create <path>            - Create new file
  list [path]              - List directory contents
  mkdir <path>             - Create directory
  rmdir <path>             - Delete directory
  help                     - Show this help message
  gen <prompt>             - Generate response using Ollama"""

    def _read_file(self, args: list[str]) -> str:
        """Read file command handler."""
        if not args:
            return "Error: No file path provided"
        path = args[0]
        try:
            return self.file_ops.read_file(path)
        except Exception as e:
            return f"Error reading file: {e}"

    def _write_file(self, args: list[str]) -> str:
        """Write file command handler."""
        if len(args) < 2:
            return "Error: No file path or content provided"
        path = args[0]
        content = " ".join(args[1:])
        try:
            self.file_ops.write_file(path, content)
            return f"Successfully wrote to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    def _delete_file(self, args: list[str]) -> str:
        """Delete file command handler."""
        if not args:
            return "Error: No file path provided"
        path = args[0]
        try:
            if self.file_ops.delete_file(path):
                return f"Successfully deleted {path}"
            return f"File not found: {path}"
        except Exception as e:
            return f"Error deleting file: {e}"

    def _create_file(self, args: list[str]) -> str:
        """Create file command handler."""
        if not args:
            return "Error: No file path provided"
        path = args[0]
        content = " ".join(args[1:]) if len(args) > 1 else ""
        try:
            self.file_ops.create_file(path, content)
            return f"Successfully created {path}"
        except Exception as e:
            return f"Error creating file: {e}"

    def _list_directory(self, args: list[str]) -> str:
        """List directory command handler."""
        path = args[0] if args else "."
        try:
            files = self.file_ops.list_directory(path)
            return "\n".join(files)
        except Exception as e:
            return f"Error listing directory: {e}"

    def _mkdir(self, args: list[str]) -> str:
        """Make directory command handler."""
        if not args:
            return "Error: No directory path provided"
        path = args[0]
        try:
            self.file_ops.create_directory(path)
            return f"Successfully created directory {path}"
        except Exception as e:
            return f"Error creating directory: {e}"

    def _rmdir(self, args: list[str]) -> str:
        """Remove directory command handler."""
        if not args:
            return "Error: No directory path provided"
        path = args[0]
        try:
            if self.file_ops.delete_directory(path):
                return f"Successfully removed directory {path}"
            return f"Directory not found: {path}"
        except Exception as e:
            return f"Error removing directory: {e}"


class SessionManager:
    """Manages persistent chat sessions per chat_id."""

    def __init__(self, sessions_dir: str, *, max_messages: int = 40):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.max_messages = int(max_messages)
        self._cache: dict[int, list[dict[str, Any]]] = {}

    def _path(self, chat_id: int) -> Path:
        return self.sessions_dir / f"session_{chat_id}.json"

    def _default_session(self) -> list[dict[str, Any]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are Orbitron, a coding kernel with access to tools for file operations. "
                    "When the user requests filesystem changes, use the tools. "
                    "All file paths MUST be relative to the workspace. "
                    "After completing tool calls, respond with a concise summary of what changed."
                ),
            }
        ]

    def _trim_in_place(self, session: list[dict[str, Any]]) -> None:
        if not session:
            session.extend(self._default_session())
            return

        first = session[0] if isinstance(session[0], dict) else None
        if not first or first.get("role") != "system":
            session[:] = self._default_session() + [m for m in session if isinstance(m, dict)]

        if self.max_messages <= 0:
            session[:] = session[:1]
            return

        # Truncate message contents to prevent context bloat
        for msg in session:
            if isinstance(msg, dict) and "content" in msg:
                content = msg["content"]
                if isinstance(content, str) and len(content) > 2000:
                    msg["content"] = content[:2000] + "\n...[truncated]"

        rest = [m for m in session[1:] if isinstance(m, dict)]
        if len(rest) > self.max_messages:
            rest = rest[-self.max_messages :]
        session[:] = [session[0]] + rest

    def get(self, chat_id: int) -> list[dict[str, Any]]:
        """Get session or create fresh one."""
        if chat_id in self._cache:
            session = self._cache[chat_id]
            self._trim_in_place(session)
            return session

        path = self._path(chat_id)
        if path.exists():
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(obj, list) and all(isinstance(x, dict) for x in obj):
                    session = obj
                else:
                    session = self._default_session()
            except Exception:
                session = self._default_session()
        else:
            session = self._default_session()

        self._trim_in_place(session)
        self._cache[chat_id] = session
        return session

    def add_message(self, chat_id: int, message: dict[str, Any]) -> None:
        """Add a message to the session and cache."""
        session = self.get(chat_id)
        session.append(message)
        self._trim_in_place(session)
        self._cache[chat_id] = session

    def save(self, chat_id: int) -> None:
        """Persist session to disk."""
        if chat_id not in self._cache:
            return
        path = self._path(chat_id)
        try:
            self._trim_in_place(self._cache[chat_id])
            path.write_text(json.dumps(self._cache[chat_id], ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def clear(self, chat_id: int) -> None:
        """Clear session cache and delete persisted file."""
        if chat_id in self._cache:
            del self._cache[chat_id]
        path = self._path(chat_id)
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass


def main():
    """Main entry point."""
    print("Orbitron Kernel v1.0.0")
    print("Type 'help' for commands or 'exit' to quit")
    
    kernel = OrbitronKernel()
    
    while True:
        try:
            user_input = input("\n> ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() == "exit":
                print("Goodbye!")
                break
            
            if user_input.lower() == "help":
                print(kernel._help())
                continue
            
            # Check for gen command
            if user_input.lower().startswith("gen "):
                prompt = user_input[4:]
                response = kernel.generate_response(prompt)
                print(response)
                continue
            
            # Parse command
            parts = user_input.split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1].split() if len(parts) > 1 else []
            
            result = kernel.process_command(command, args)
            print(result)
            
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except EOFError:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
