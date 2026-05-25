"""MarkdownBuilder - Fluent builder for structured Markdown documents.

Produces Markdown strings that can be fed to Pandoc for conversion
to professionally styled DOCX files.

Supports:
- YAML metadata (title, author, date, lang)
- Cover pages with title, subtitle, author, date
- Headings (H1-H6)
- Paragraphs with formatting (bold, italic, underline)
- Bullet and numbered lists
- Tables with alignment
- Horizontal rules and page breaks
- Callout/admonition blocks (info, warning, tip, note)
- Image references with captions
- Code blocks with syntax highlighting
- Table of contents (TOC)
- Custom raw Markdown passthrough
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from OrbitronUtils.dates import months_de, format_date_de


class MarkdownBuilder:
    """Build a Markdown document programmatically with professional formatting.

    Usage::

        md = (
            MarkdownBuilder()
            .add_metadata(title="Quarterly Report", author="Orbitron", lang="de")
            .add_cover_page(subtitle="Q4 2026 Results")
            .add_toc()
            .add_heading("Executive Summary")
            .add_paragraph("Revenue increased by 12%.")
            .add_callout("Key Insight", "Growth exceeded expectations.", style="tip")
            .add_page_break()
            .add_heading("Financial Overview")
            .add_table(headers=["Quarter", "Revenue"], rows=[["Q1", "$1.2M"]])
            .build()
        )
    """

    def __init__(self) -> None:
        self._lines: list[str] = []
        self._has_metadata: bool = False
        self._has_toc: bool = False
        self._has_cover: bool = False

    # -- YAML Metadata (Pandoc) -----------------------------------------------

    def add_metadata(
        self,
        title: str = "",
        author: str = "",
        date: str = "",
        lang: str = "de",
        subtitle: str = "",
        abstract: str = "",
    ) -> MarkdownBuilder:
        """Add YAML metadata block for Pandoc.

        This should be called first, before any content.
        The metadata controls document properties like title, author,
        language, and other Pandoc settings.

        Args:
            title: Document title.
            author: Document author.
            date: Document date (defaults to today if empty and lang is set).
            lang: Language code (default: "de" for German).
            subtitle: Document subtitle.
            abstract: Document abstract/summary.
        """
        if self._has_metadata:
            # Append to existing metadata — remove closing --- to add more fields
            if self._lines and self._lines[-1] == "---":
                self._lines.pop()
        else:
            self._lines.append("---")

        if title:
            self._lines.append(f'title: "{title}"')
        if subtitle:
            self._lines.append(f'subtitle: "{subtitle}"')
        if author:
            self._lines.append(f'author: "{author}"')
        if date:
            self._lines.append(f'date: "{date}"')
        elif lang:
            today = datetime.now()
            if lang == "de":
                self._lines.append(f'date: "{format_date_de(today)}"')
            else:
                self._lines.append(f'date: "{today.strftime("%B %d, %Y")}"')

        if lang:
            self._lines.append(f'lang: {lang}')
        if abstract:
            self._lines.append(f'abstract: "{abstract}"')

        # Pandoc settings for better output
        self._lines.append("documentclass: article")
        self._lines.append("papersize: a4")
        self._lines.append("fontsize: 11pt")
        self._lines.append("linestretch: 1.15")
        self._lines.append("toc-own-page: true")
        self._lines.append("numbersections: true")
        self._lines.append("secnums: true")
        self._lines.append("shift-heading-level-by: -1")
        self._lines.append("highlight-style: pygments")

        self._lines.append("---")
        self._lines.append("")
        self._has_metadata = True
        return self

    # -- Cover Page ------------------------------------------------------------

    def add_cover_page(
        self,
        title: str = "",
        subtitle: str = "",
        author: str = "",
        date: str = "",
        organization: str = "",
    ) -> MarkdownBuilder:
        """Add a professional cover page.

        Creates a centered title page with title, subtitle, author,
        date, and organization. Includes a page break after.

        Args:
            title: Main title (large, bold).
            subtitle: Subtitle below the title.
            author: Author name(s).
            date: Date string.
            organization: Organization/company name.
        """
        self._lines.append("\\newpage")
        self._lines.append("")

        # Center everything on the cover page
        self._lines.append("<div style=\"text-align: center;\">")
        self._lines.append("")
        self._lines.append("&nbsp;")
        self._lines.append("")
        self._lines.append("&nbsp;")
        self._lines.append("")

        if title:
            self._lines.append(f"## {title}")
            self._lines.append("")

        if subtitle:
            self._lines.append(f"### {subtitle}")
            self._lines.append("")

        self._lines.append("---")
        self._lines.append("")

        if author:
            self._lines.append(f"**{author}**")
            self._lines.append("")

        if organization:
            self._lines.append(f"*{organization}*")
            self._lines.append("")

        if date:
            self._lines.append(f"{date}")
            self._lines.append("")

        self._lines.append("</div>")
        self._lines.append("")
        self._lines.append("\\newpage")
        self._lines.append("")
        self._has_cover = True
        return self

    # -- Table of Contents -----------------------------------------------------

    def add_toc(self) -> MarkdownBuilder:
        """Add a table of contents."""
        self._lines.append("\\newpage")
        self._lines.append("")
        self._lines.append("# Inhaltsverzeichnis")
        self._lines.append("")
        self._lines.append("\\tableofcontents")
        self._lines.append("")
        self._lines.append("\\newpage")
        self._lines.append("")
        self._has_toc = True
        return self

    # -- Block elements --------------------------------------------------------

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

    def add_table(
        self,
        headers: list[str],
        rows: list[list[str]],
        align: Optional[list[str]] = None,
    ) -> MarkdownBuilder:
        """Add a Markdown table with optional column alignment.

        Args:
            headers: Column header texts.
            rows: Each inner list is one row; must match headers length.
            align: Optional list of alignment specs per column.
                   Each value is 'left', 'center', or 'right'.
        """
        header_line = "| " + " | ".join(headers) + " |"

        # Build separator with alignment
        if align:
            separators = []
            for a in align:
                if a == "center":
                    separators.append(":---:")
                elif a == "right":
                    separators.append("---:")
                else:  # left or default
                    separators.append("---")
            separator_line = "| " + " | ".join(separators) + " |"
        else:
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

    def add_page_break(self) -> MarkdownBuilder:
        """Add a page break."""
        self._lines.append("\\newpage")
        self._lines.append("")
        return self

    def add_callout(
        self,
        title: str,
        content: str,
        style: str = "info",
    ) -> MarkdownBuilder:
        """Add a callout/admonition block.

        Creates a visually distinct block for tips, warnings, notes, etc.

        Args:
            title: Callout title.
            content: Callout body text.
            style: One of 'info', 'warning', 'tip', 'note', 'important'.
        """
        style_markers = {
            "info": "ℹ️",
            "warning": "⚠️",
            "tip": "💡",
            "note": "📝",
            "important": "❗",
        }
        marker = style_markers.get(style, "📝")

        self._lines.append(f"> **{marker} {title}**")
        self._lines.append(f">")
        # Multi-line content support
        for line in content.strip().split("\n"):
            self._lines.append(f"> {line}")
        self._lines.append("")
        return self

    def add_image(
        self,
        path: str,
        caption: str = "",
        width: str = "",
    ) -> MarkdownBuilder:
        """Add an image with optional caption and width.

        Args:
            path: Path or URL to the image.
            caption: Optional caption below the image.
            width: Optional width specification (e.g., '80%', '300px').
        """
        if width:
            self._lines.append(f"![{caption}]({path}){{width={width}}}")
        else:
            self._lines.append(f"![{caption}]({path})")
        if caption:
            self._lines.append("")
        return self

    def add_code_block(self, code: str, language: str = "") -> MarkdownBuilder:
        """Add a fenced code block with optional syntax highlighting.

        Args:
            code: The code content.
            language: Language identifier for syntax highlighting (e.g., 'python', 'json').
        """
        self._lines.append(f"```{language}")
        self._lines.append(code)
        self._lines.append("```")
        self._lines.append("")
        return self

    def add_blockquote(self, text: str, attribution: str = "") -> MarkdownBuilder:
        """Add a blockquote with optional attribution.

        Args:
            text: The quoted text.
            attribution: Optional attribution (e.g., "— Albert Einstein").
        """
        for line in text.strip().split("\n"):
            self._lines.append(f"> {line}")
        if attribution:
            self._lines.append(f"> — {attribution}")
        self._lines.append("")
        return self

    def add_raw(self, text: str) -> MarkdownBuilder:
        """Add raw Markdown text (pass-through)."""
        self._lines.append(text)
        return self

    # -- Inline formatting helpers -------------------------------------------

    @staticmethod
    def bold(text: str) -> str:
        """Wrap text in bold markers."""
        return f"**{text}**"

    @staticmethod
    def italic(text: str) -> str:
        """Wrap text in italic markers."""
        return f"*{text}*"

    @staticmethod
    def strikethrough(text: str) -> str:
        """Wrap text in strikethrough markers."""
        return f"~~{text}~~"

    @staticmethod
    def code(text: str) -> str:
        """Wrap text in inline code markers."""
        return f"`{text}`"

    @staticmethod
    def link(text: str, url: str) -> str:
        """Create a hyperlink."""
        return f"[{text}]({url})"

    # -- Build ----------------------------------------------------------------

    def build(self) -> str:
        """Return the assembled Markdown string."""
        # Collapse multiple trailing blank lines into one
        result = "\n".join(self._lines)
        return result.rstrip() + "\n"