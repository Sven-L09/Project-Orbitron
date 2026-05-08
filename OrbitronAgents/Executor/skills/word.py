"""Word Processing Skill for the Executor Agent.

Provides document creation and text formatting capabilities.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("Executor.WordSkill")


from .skill_base import ExecutorSkill

class WordSkill(ExecutorSkill):
    """Skill for word processing and document creation.

    Note: This class does NOT inherit from ExecutorSkill to avoid
    circular dependencies. It's used directly by ExecutorAgent.
    """

    def __init__(self, workspace: str | None = None):
        self.name = "word"
        self.description = "Word processing, document creation, and text formatting"
        self.workspace = workspace
        self._tools: list[dict[str, Any]] = []
        self._handlers: dict[str, Any] = {}
        self._setup_tools()

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

    def _setup_tools(self) -> None:
        """Register word processing tools."""

        # Tool: Create Word document
        self.register_tool(
            "create_document",
            {
                "description": "Create a new Word document with content",
                "parameters": {
                    "type": "object",
                    "required": ["filename", "title", "content"],
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Output filename (e.g., 'report.docx')"
                        },
                        "title": {
                            "type": "string",
                            "description": "Document title"
                        },
                        "content": {
                            "type": "string",
                            "description": "Main document content"
                        },
                        "format": {
                            "type": "string",
                            "enum": ["docx", "pdf", "txt", "md"],
                            "description": "Document format (default: docx)"
                        }
                    }
                }
            },
            self._handle_create_document
        )

        # Tool: Create report
        self.register_tool(
            "create_report",
            {
                "description": "Create a structured report with sections",
                "parameters": {
                    "type": "object",
                    "required": ["filename", "title", "sections"],
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Output filename"
                        },
                        "title": {
                            "type": "string",
                            "description": "Report title"
                        },
                        "sections": {
                            "type": "array",
                            "description": "Report sections",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "heading": {"type": "string"},
                                    "content": {"type": "string"}
                                }
                            }
                        }
                    }
                }
            },
            self._handle_create_report
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

    def _handle_create_document(self, args: dict[str, Any]) -> str:
        """Handle create_document tool call."""
        try:
            filename = args.get("filename", "")
            title = args.get("title", "")
            content = args.get("content", "")
            fmt = args.get("format", "docx")

            if not filename:
                return json.dumps({"ok": False, "error": "Filename is required"})

            # Create document content based on format
            if fmt == "txt":
                doc_content = f"{title}\n{'=' * len(title)}\n\n{content}"
            elif fmt == "md":
                doc_content = f"# {title}\n\n{content}"
            elif fmt == "pdf":
                # PDF requires external library, create placeholder
                doc_content = json.dumps({
                    "title": title,
                    "content": content,
                    "format": "pdf",
                    "note": "PDF generation requires python-docx and pdfkit"
                })
            else:  # docx
                doc_content = json.dumps({
                    "title": title,
                    "content": content,
                    "format": "docx",
                    "note": "DOCX generation requires python-docx library"
                })

            # Write to file
            full_path = self._resolve_path(filename)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(doc_content, encoding="utf-8")

            return json.dumps({
                "ok": True,
                "message": f"Document created: {filename}",
                "path": str(full_path)
            })
        except Exception as e:
            logger.exception("[WordSkill] create_document failed")
            return json.dumps({"ok": False, "error": str(e)})

    def _handle_create_report(self, args: dict[str, Any]) -> str:
        """Handle create_report tool call."""
        try:
            filename = args.get("filename", "")
            title = args.get("title", "")
            sections = args.get("sections", [])

            if not filename:
                return json.dumps({"ok": False, "error": "Filename is required"})

            # Build report content
            sections_text = "\n\n".join(
                f"## {s.get('heading', 'Section')}\n\n{s.get('content', '')}"
                for s in sections
            )

            report_content = f"# {title}\n\n{sections_text}"

            # Write to file
            full_path = self._resolve_path(filename)
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(report_content, encoding="utf-8")

            return json.dumps({
                "ok": True,
                "message": f"Report created: {filename}",
                "path": str(full_path),
                "sections_count": len(sections)
            })
        except Exception as e:
            logger.exception("[WordSkill] create_report failed")
            return json.dumps({"ok": False, "error": str(e)})
