"""OrbitronWordSystem - Pandoc-based professional Word document generation.

Provides:
- PandocGenerator: Converts Markdown to styled DOCX via Pandoc
- MarkdownBuilder: Fluent builder for structured Markdown documents
  with metadata, cover pages, TOC, callouts, and more
- DocxPostProcessor: Post-processes DOCX files with python-docx to add
  headers, footers, TOC fields, and remove duplicate titles
"""

from .generator import PandocGenerator
from .markdown_builder import MarkdownBuilder
from .docx_post_processor import post_process_docx

__all__ = ["PandocGenerator", "MarkdownBuilder", "post_process_docx"]