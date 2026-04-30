"""Main kernel module for Orbitron."""

import json
import os
from pathlib import Path
from typing import Any

try:
    # Package import (recommended): python -m OrbitronKernel.main / OrbitronSystem/main.py
    from .OllamaConnector import OllamaConnector
    from .config import Config
    from .file_operations import FileOperations
except ImportError:
    # Script import fallback (legacy): run from within OrbitronKernel directory
    from OllamaConnector import OllamaConnector
    from config import Config
    from file_operations import FileOperations


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

        self._tools = self._build_tools_schema()
        sessions_dir = self.config.get("kernel.sessions_dir") or str(Path.home() / ".orbitron" / "sessions")
        self._sessions = SessionManager(sessions_dir, max_messages=40)

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

    def run_chat(self, messages: list[dict[str, Any]], *, max_rounds: int = 10) -> str:
        """Run an agent loop on an existing message list.

        This is suitable for multi-turn chat (e.g., Telegram) where you want to
        keep `messages` around per user/chat id.
        """
        for _ in range(max_rounds):
            resp = self.ollama.chat(messages, tools=self._tools, stream=False, think=None)
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

            return str(msg.get("content") or "")

        return "Error: tool loop exceeded max rounds"

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
                    "description": "Replace the full contents of an existing file in the workspace.",
                    "parameters": {
                        "type": "object",
                        "required": ["path", "content"],
                        "properties": {
                            "path": {"type": "string", "description": "Relative file path"},
                            "content": {"type": "string", "description": "New full file contents"},
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
        content = args.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        if not self.file_ops.file_exists(path):
            return json.dumps({"ok": False, "error": "File does not exist", "path": path})
        self.file_ops.write_file(path, content)
        return json.dumps({"ok": True, "action": "update_file", "path": path})

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
