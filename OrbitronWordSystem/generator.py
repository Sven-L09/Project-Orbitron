"""PandocGenerator - Converts Markdown to professional DOCX via Pandoc.

Uses a reference document (template.docx) to apply consistent styling
across all generated Word documents.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from .markdown_builder import MarkdownBuilder

logger = logging.getLogger("OrbitronWordSystem.PandocGenerator")


class PandocGenerator:
    """Generate professional Word documents from Markdown using Pandoc.

    If a reference document (template.docx) is available, it is passed to
    Pandoc via ``--reference-doc`` so that the output inherits all styles,
    fonts, colours and layout from that template.
    """

    def __init__(self, reference_doc_path: str | None = None) -> None:
        self._ensure_pandoc()
        self.reference_doc_path = self._resolve_reference_doc(reference_doc_path)

    # ------------------------------------------------------------------
    # Pandoc availability
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_pandoc() -> None:
        """Make sure the Pandoc binary is available.

        If Pandoc is not found on the system, this automatically downloads
        it via ``pypandoc.download_pandoc()`` so that document generation
        works without requiring a system-level installation.
        """
        try:
            import pypandoc
            pypandoc.get_pandoc_path()  # raises OSError if not found
        except OSError:
            logger.info("[PandocGenerator] Pandoc binary not found – downloading via pypandoc…")
            try:
                pypandoc.download_pandoc()
                logger.info("[PandocGenerator] Pandoc downloaded successfully")
            except Exception as exc:
                logger.warning("[PandocGenerator] Failed to download Pandoc: %s", exc)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def markdown_to_docx(
        self,
        markdown_content: str,
        output_path: str,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Convert a Markdown string to a DOCX file.

        Args:
            markdown_content: The document body in Markdown.
            output_path: Destination path for the .docx file.
            title: Optional document title (written as Pandoc metadata).

        Returns:
            Dict with ``ok``, ``path``, ``size_kb``, and optional ``error``.
        """
        try:
            import pypandoc  # deferred import
        except ImportError:
            return {
                "ok": False,
                "error": (
                    "pypandoc is not installed. Install it with: "
                    "pip install pypandoc"
                ),
            }

        # Verify Pandoc binary is available
        available, msg = self.check_pandoc_available()
        if not available:
            return {"ok": False, "error": msg}

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        tmp_md: Path | None = None
        try:
            # Write Markdown to a temporary file so Pandoc can read it
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".md",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(markdown_content)
                tmp_md = Path(tmp.name)

            # Build extra arguments for Pandoc
            extra_args: list[str] = []
            if self.reference_doc_path:
                extra_args.append(
                    f"--reference-doc={self.reference_doc_path}"
                )
            if title:
                extra_args.append(f"--metadata=title:{title}")

            pypandoc.convert_file(
                str(tmp_md),
                to="docx",
                format="md",
                outputfile=str(output),
                extra_args=extra_args if extra_args else None,
            )

            # Verify output
            if not output.exists():
                return {
                    "ok": False,
                    "error": f"Pandoc completed but output file not found: {output}",
                }
            size_kb = round(output.stat().st_size / 1024, 1)

            return {
                "ok": True,
                "path": str(output),
                "size_kb": size_kb,
                "message": f"Document created: {output.name}",
            }

        except Exception as exc:
            logger.exception("[PandocGenerator] markdown_to_docx failed")
            return {"ok": False, "error": str(exc)}
        finally:
            # Always clean up the temporary Markdown file
            if tmp_md and tmp_md.exists():
                try:
                    tmp_md.unlink()
                except OSError:
                    pass

    def structured_to_docx(
        self,
        title: str,
        sections: list[dict[str, str]],
        output_path: str,
    ) -> dict[str, Any]:
        """Convert a structured title + sections dict to DOCX.

        Args:
            title: Document title (heading level 1).
            sections: List of dicts with ``heading`` and ``content`` keys.
            output_path: Destination path for the .docx file.

        Returns:
            Same dict shape as ``markdown_to_docx``.
        """
        builder = MarkdownBuilder()
        builder.add_title(title, level=1)

        for section in sections:
            heading = section.get("heading", "")
            content = section.get("content", "")
            if heading:
                builder.add_heading(heading, level=2)
            if content:
                builder.add_paragraph(content)

        markdown = builder.build()
        return self.markdown_to_docx(
            markdown_content=markdown,
            output_path=output_path,
            title=title,
        )

    def check_pandoc_available(self) -> tuple[bool, str]:
        """Check whether Pandoc is installed and accessible.

        If Pandoc is not found, attempts to download it automatically via
        ``pypandoc.download_pandoc()`` before reporting failure.

        Returns:
            (available, message) tuple.
        """
        try:
            import pypandoc  # noqa: F811
            path = pypandoc.get_pandoc_path()
            version = pypandoc.get_pandoc_version()
            return True, f"Pandoc {version} at {path}"
        except ImportError:
            return False, "pypandoc is not installed"
        except OSError:
            # Try auto-downloading Pandoc
            try:
                import pypandoc  # noqa: F811
                logger.info("[PandocGenerator] Pandoc binary not found – attempting auto-download…")
                pypandoc.download_pandoc()
                path = pypandoc.get_pandoc_path()
                version = pypandoc.get_pandoc_version()
                return True, f"Pandoc {version} at {path} (auto-installed)"
            except Exception as exc:
                return False, f"Pandoc binary not found and auto-download failed: {exc}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_reference_doc(path: str | None) -> Path | None:
        """Resolve the reference document path.

        Priority:
        1. Explicit path provided by the caller.
        2. ``template.docx`` next to this module.
        3. ``None`` (Pandoc uses default styling).
        """
        if path:
            p = Path(path).resolve()
            if p.exists():
                return p
            logger.warning("[PandocGenerator] Reference doc not found: %s", p)

        # Default: template.docx in the same package directory
        default = Path(__file__).parent / "template.docx"
        if default.exists():
            return default

        logger.warning(
            "[PandocGenerator] No reference doc found; "
            "Pandoc will use default styling"
        )
        return None