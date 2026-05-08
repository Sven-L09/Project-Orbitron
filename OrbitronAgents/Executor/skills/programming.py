"""Programming Skill for the Executor Agent.

Provides file operations and code generation capabilities.
"""

import json
import logging
from pathlib import Path
from typing import Any

from .skill_base import ExecutorSkill

logger = logging.getLogger("Executor.ProgrammingSkill")


class ProgrammingSkill(ExecutorSkill):
    """Skill for programming tasks - code generation, modification, and analysis."""

    def __init__(self):
        super().__init__(
            name="programming",
            description="Code generation, modification, and programming tasks"
        )
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Register programming tools."""

        # Tool: Create a new file with code
        self.register_tool(
            "create_file",
            {
                "description": "Create a new file. Content is optional - if not provided, the Executor will generate it via LLM based on the description.",
                "parameters": {
                    "type": "object",
                    "required": ["filename"],
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Full path and filename (e.g., 'src/main.py')"
                        },
                        "content": {
                            "type": "string",
                            "description": "The code content to write (optional - Executor generates if omitted)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Description of what the file should contain (used for LLM generation when content is omitted)"
                        },
                        "language": {
                            "type": "string",
                            "description": "Programming language (optional, for syntax highlighting)"
                        }
                    }
                }
            },
            self._handle_create_file
        )

        # Tool: Modify existing file
        self.register_tool(
            "modify_file",
            {
                "description": "Modify an existing file by replacing content",
                "parameters": {
                    "type": "object",
                    "required": ["filename", "old_content", "new_content"],
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Path to the file to modify"
                        },
                        "old_content": {
                            "type": "string",
                            "description": "The exact content to replace"
                        },
                        "new_content": {
                            "type": "string",
                            "description": "The new content to insert"
                        }
                    }
                }
            },
            self._handle_modify_file
        )

        # Tool: Read file content
        self.register_tool(
            "read_file",
            {
                "description": "Read the content of an existing file",
                "parameters": {
                    "type": "object",
                    "required": ["filename"],
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Path to the file to read"
                        }
                    }
                }
            },
            self._handle_read_file
        )

        # Tool: Create directory
        self.register_tool(
            "create_directory",
            {
                "description": "Create a new directory",
                "parameters": {
                    "type": "object",
                    "required": ["dirname"],
                    "properties": {
                        "dirname": {
                            "type": "string",
                            "description": "Path to the directory to create"
                        }
                    }
                }
            },
            self._handle_create_directory
        )

        # Tool: List directory
        self.register_tool(
            "list_directory",
            {
                "description": "List contents of a directory",
                "parameters": {
                    "type": "object",
                    "required": ["dirname"],
                    "properties": {
                        "dirname": {
                            "type": "string",
                            "description": "Path to the directory to list"
                        }
                    }
                }
            },
            self._handle_list_directory
        )

    def _handle_create_file(self, args: dict[str, Any]) -> str:
        """Handle create_file tool call."""
        try:
            filename = args.get("filename", "")
            content = args.get("content", "")

            if not filename:
                return json.dumps({"ok": False, "error": "Filename is required"})

            # Write file
            full_path = self._resolve_path(filename)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")

            return json.dumps({
                "ok": True,
                "message": f"File created: {filename}",
                "path": str(full_path)
            })
        except Exception as e:
            logger.exception("[ProgrammingSkill] create_file failed")
            return json.dumps({"ok": False, "error": str(e)})

    def _handle_modify_file(self, args: dict[str, Any]) -> str:
        """Handle modify_file tool call."""
        try:
            filename = args.get("filename", "")
            old_content = args.get("old_content", "")
            new_content = args.get("new_content", "")

            if not filename:
                return json.dumps({"ok": False, "error": "Filename is required"})

            # Read existing file
            full_path = self._resolve_path(filename)
            if not full_path.exists():
                return json.dumps({"ok": False, "error": f"File not found: {filename}"})

            content = full_path.read_text(encoding="utf-8")

            # Replace content
            if old_content not in content:
                return json.dumps({
                    "ok": False,
                    "error": "Old content not found in file",
                    "hint": "The exact content must match including whitespace"
                })

            new_content_full = content.replace(old_content, new_content)
            full_path.write_text(new_content_full, encoding="utf-8")

            return json.dumps({
                "ok": True,
                "message": f"File modified: {filename}",
                "path": str(full_path)
            })
        except Exception as e:
            logger.exception("[ProgrammingSkill] modify_file failed")
            return json.dumps({"ok": False, "error": str(e)})

    def _handle_read_file(self, args: dict[str, Any]) -> str:
        """Handle read_file tool call."""
        try:
            filename = args.get("filename", "")

            if not filename:
                return json.dumps({"ok": False, "error": "Filename is required"})

            full_path = self._resolve_path(filename)
            if not full_path.exists():
                return json.dumps({"ok": False, "error": f"File not found: {filename}"})

            content = full_path.read_text(encoding="utf-8")

            # Truncate long content
            max_length = 10000
            if len(content) > max_length:
                content = content[:max_length] + f"\n... [content truncated, {len(content)} chars total]"

            return json.dumps({
                "ok": True,
                "content": content,
                "length": len(content)
            })
        except Exception as e:
            logger.exception("[ProgrammingSkill] read_file failed")
            return json.dumps({"ok": False, "error": str(e)})

    def _handle_create_directory(self, args: dict[str, Any]) -> str:
        """Handle create_directory tool call."""
        try:
            dirname = args.get("dirname", "")

            if not dirname:
                return json.dumps({"ok": False, "error": "Directory name is required"})

            full_path = self._resolve_path(dirname)
            full_path.mkdir(parents=True, exist_ok=True)

            return json.dumps({
                "ok": True,
                "message": f"Directory created: {dirname}",
                "path": str(full_path)
            })
        except Exception as e:
            logger.exception("[ProgrammingSkill] create_directory failed")
            return json.dumps({"ok": False, "error": str(e)})

    def _handle_list_directory(self, args: dict[str, Any]) -> str:
        """Handle list_directory tool call."""
        try:
            dirname = args.get("dirname", ".")

            full_path = self._resolve_path(dirname)
            if not full_path.exists():
                return json.dumps({"ok": False, "error": f"Directory not found: {dirname}"})

            items = []
            for item in full_path.iterdir():
                items.append({
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None
                })

            return json.dumps({
                "ok": True,
                "dirname": str(full_path),
                "items": items,
                "count": len(items)
            })
        except Exception as e:
            logger.exception("[ProgrammingSkill] list_directory failed")
            return json.dumps({"ok": False, "error": str(e)})
