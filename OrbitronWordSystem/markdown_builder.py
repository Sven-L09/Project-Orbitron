"""MarkdownBuilder - Fluent builder for structured Markdown documents.

Produces Markdown strings that can be fed to Pandoc for conversion
to professionally styled DOCX files.
"""

from __future__ import annotations


class MarkdownBuilder:
    """Build a Markdown document programmatically.

    Usage::

        md = (
            MarkdownBuilder()
            .add_title("Quarterly Report")
            .add_heading("Executive Summary")
            .add_paragraph("Revenue increased by 12%.")
            .add_bullet_list(["Item A", "Item B"])
            .build()
        )
    """

    def __init__(self) -> None:
        self._lines: list[str] = []

    # -- Block elements -------------------------------------------------------

    def add_title(self, title: str, level: int = 1) -> MarkdownBuilder:
        """Add a heading (default level 1 = document title)."""
        prefix = "#" * max(1, min(6, level))
        self._lines.append(f"{prefix} {title}")
        self._lines.append("")
        return self

    def add_heading(self, text: str, level: int = 2) -> MarkdownBuilder:
        """Add a sub-heading."""
        prefix = "#" * max(1, min(6, level))
        self._lines.append(f"{prefix} {text}")
        self._lines.append("")
        return self

    def add_paragraph(self, text: str) -> MarkdownBuilder:
        """Add a paragraph of text."""
        self._lines.append(text.strip())
        self._lines.append("")
        return self

    def add_bullet_list(self, items: list[str]) -> MarkdownBuilder:
        """Add an unordered (bullet) list."""
        for item in items:
            self._lines.append(f"- {item}")
        self._lines.append("")
        return self

    def add_numbered_list(self, items: list[str]) -> MarkdownBuilder:
        """Add an ordered (numbered) list."""
        for i, item in enumerate(items, 1):
            self._lines.append(f"{i}. {item}")
        self._lines.append("")
        return self

    def add_table(self, headers: list[str], rows: list[list[str]]) -> MarkdownBuilder:
        """Add a Markdown table.

        Args:
            headers: Column header texts.
            rows: Each inner list is one row; must match headers length.
        """
        header_line = "| " + " | ".join(headers) + " |"
        separator_line = "| " + " | ".join("---" for _ in headers) + " |"
        self._lines.append(header_line)
        self._lines.append(separator_line)
        for row in rows:
            # Pad shorter rows with empty cells
            padded = list(row) + [""] * (len(headers) - len(row))
            self._lines.append("| " + " | ".join(padded[: len(headers)]) + " |")
        self._lines.append("")
        return self

    def add_horizontal_rule(self) -> MarkdownBuilder:
        """Add a horizontal rule (section divider)."""
        self._lines.append("---")
        self._lines.append("")
        return self

    def add_raw(self, text: str) -> MarkdownBuilder:
        """Add raw Markdown text (pass-through)."""
        self._lines.append(text)
        return self

    # -- Build ----------------------------------------------------------------

    def build(self) -> str:
        """Return the assembled Markdown string."""
        # Collapse multiple trailing blank lines into one
        result = "\n".join(self._lines)
        return result.rstrip() + "\n"