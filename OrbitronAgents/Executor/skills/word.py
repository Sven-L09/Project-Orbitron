"""Word Processing Skill for the Executor Agent.

Provides professional DOCX generation via Pandoc, using the
OrbitronWordSystem template for consistent styling.

Enhanced features:
- Professional cover pages with title, subtitle, author, date
- Table of contents (TOC)
- Callout/admonition blocks (info, warning, tip, note)
- Page breaks
- YAML metadata for Pandoc (language, fonts, margins)
- German date formatting
- Image embedding with captions
- Code blocks with syntax highlighting
"""

import json
import logging
from typing import Any

from .skill_base import ExecutorSkill

logger = logging.getLogger("Executor.WordSkill")


class WordSkill(ExecutorSkill):
    """Skill for word processing and document creation via Pandoc.

    Provides tools for creating professional Word documents with:
    - Full Markdown formatting support
    - Cover pages and metadata
    - Table of contents
    - Callout blocks (tips, warnings, notes)
    - Page breaks
    - Tables with alignment
    - Code blocks with syntax highlighting
    """

    def __init__(self, workspace: str | None = None):
        super().__init__(
            name="word",
            description="Word processing, document creation, and report generation using Pandoc",
        )
        if workspace:
            self.set_workspace(workspace)
        self._pandoc_generator = None  # lazy-initialised
        self._setup_tools()

    # ------------------------------------------------------------------
    # Lazy initialisation
    # ------------------------------------------------------------------

    def _get_generator(self):
        """Lazy-initialise the PandocGenerator (defer import until needed)."""
        if self._pandoc_generator is None:
            from OrbitronWordSystem import PandocGenerator
            self._pandoc_generator = PandocGenerator()
        return self._pandoc_generator

    # ------------------------------------------------------------------
    # Tool registration
    # ------------------------------------------------------------------

    def _setup_tools(self) -> None:
        """Register word processing tools."""

        self.register_tool(
            "create_document",
            {
                "description": (
                    "Create a professional Word document from Markdown content. "
                    "The content parameter accepts full Markdown formatting "
                    "(headings, lists, tables, etc.) and produces a styled DOCX file. "
                    "Supports YAML metadata, cover pages, TOC, callouts, page breaks, "
                    "and all advanced Markdown features. "
                    "IMPORTANT: The generated document automatically includes professional "
                    "headers (document title), footers (date + page numbers), proper TOC fields, "
                    "and removes duplicate titles. You do NOT need to write custom Python scripts "
                    "or use python-docx directly — this tool handles everything."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["filename", "content"],
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Output filename (e.g., 'report.docx')",
                        },
                        "content": {
                            "type": "string",
                            "description": (
                                "Document content in Markdown format. "
                                "Supports headings (# H1, ## H2, etc.), "
                                "bullet lists (- item), numbered lists (1. item), "
                                "tables, bold (**text**), italic (*text*), "
                                "callouts (> **💡 Tip** > content), "
                                "page breaks (\\newpage), "
                                "and all standard Markdown syntax."
                            ),
                        },
                        "title": {
                            "type": "string",
                            "description": "Optional document title (used as Pandoc metadata and in header)",
                        },
                        "author": {
                            "type": "string",
                            "description": "Optional document author",
                        },
                    },
                },
            },
            self._handle_create_document,
        )

        self.register_tool(
            "create_report",
            {
                "description": (
                    "Create a structured Word report with a title and multiple sections. "
                    "Each section has a heading and Markdown content. "
                    "Produces a professionally styled DOCX file with cover page, "
                    "table of contents, headers (document title), footers (date + page numbers), "
                    "and proper formatting. "
                    "IMPORTANT: The generated document automatically includes professional "
                    "headers, footers, TOC fields, and removes duplicate titles. "
                    "You do NOT need to write custom Python scripts or use python-docx directly — "
                    "this tool handles everything. NEVER write a generate_doc.py script or use "
                    "python-docx manually. Always use create_report or create_document instead."
                ),
                "parameters": {
                    "type": "object",
                    "required": ["filename", "title", "sections"],
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Output filename (e.g., 'quarterly_report.docx')",
                        },
                        "title": {
                            "type": "string",
                            "description": "Report title (also used in document header)",
                        },
                        "sections": {
                            "type": "array",
                            "description": "Report sections, each with 'heading' and 'content'",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "heading": {"type": "string"},
                                    "content": {"type": "string"},
                                    "level": {
                                        "type": "integer",
                                        "description": "Heading level (2=H2, 3=H3). Default: 2",
                                    },
                                },
                            },
                        },
                        "author": {
                            "type": "string",
                            "description": "Optional report author",
                        },
                        "subtitle": {
                            "type": "string",
                            "description": "Optional report subtitle",
                        },
                        "include_toc": {
                            "type": "boolean",
                            "description": "Whether to include a table of contents (default: true)",
                        },
                    },
                },
            },
            self._handle_create_report,
        )

    # ------------------------------------------------------------------
    # Tool handlers
    # ------------------------------------------------------------------

    def _handle_create_document(self, args: dict[str, Any]) -> str:
        """Handle create_document tool call."""
        try:
            filename = args.get("filename", "")
            content = args.get("content", "")
            title = args.get("title", "")
            author = args.get("author", "")

            if not filename:
                return json.dumps({"ok": False, "error": "Filename is required"})

            generator = self._get_generator()
            result = generator.markdown_to_docx(
                markdown_content=content,
                output_path=str(self._resolve_path(filename)),
                title=title or None,
            )
            return json.dumps(result)

        except Exception as e:
            logger.exception("[WordSkill] create_document failed")
            return json.dumps({"ok": False, "error": str(e)})

    def _handle_create_report(self, args: dict[str, Any]) -> str:
        """Handle create_report tool call."""
        try:
            filename = args.get("filename", "")
            title = args.get("title", "")
            sections = args.get("sections", [])
            author = args.get("author", "")
            subtitle = args.get("subtitle", "")
            include_toc = args.get("include_toc", True)

            if not filename:
                return json.dumps({"ok": False, "error": "Filename is required"})

            generator = self._get_generator()
            result = generator.structured_to_docx(
                title=title,
                sections=sections,
                output_path=str(self._resolve_path(filename)),
                author=author,
                lang="de",
                subtitle=subtitle,
                include_toc=include_toc,
            )
            return json.dumps(result)

        except Exception as e:
            logger.exception("[WordSkill] create_report failed")
            return json.dumps({"ok": False, "error": str(e)})