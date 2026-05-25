"""DocxPostProcessor - Post-processes Pandoc-generated DOCX files with python-docx.

Adds professional features that Pandoc cannot produce on its own:
- Document headers with title and bottom border
- Document footers with page numbers and date
- Proper TOC field insertion
- Image embedding from file paths
- Cover page cleanup (remove duplicate titles)

This module is called AFTER Pandoc conversion to enhance the output.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from OrbitronUtils.dates import format_date_de

logger = logging.getLogger("OrbitronWordSystem.DocxPostProcessor")


def post_process_docx(
    docx_path: str,
    title: str = "",
    author: str = "",
    date: str = "",
    include_toc: bool = True,
    header_text: str = "",
    footer_text: str = "",
    remove_duplicate_titles: bool = True,
) -> dict[str, Any]:
    """Post-process a Pandoc-generated DOCX file to add professional features.

    This function opens the generated DOCX with python-docx and enhances it
    with headers, footers, proper TOC fields, and other features that Pandoc
    cannot produce.

    Args:
        docx_path: Path to the DOCX file to post-process.
        title: Document title (used in header if header_text not provided).
        author: Document author (not used in post-processing currently).
        date: Date string for footer (auto-generated if empty).
        include_toc: Whether to ensure a proper TOC field exists.
        header_text: Custom header text (defaults to title if empty).
        footer_text: Custom footer text (defaults to "date | Seite X" if empty).
        remove_duplicate_titles: Whether to remove duplicate title/subtitle
            headings that appear both on the cover page and in the body.

    Returns:
        Dict with ``ok``, ``path``, and optional ``error``.
    """
    try:
        from docx import Document
        from docx.shared import Pt, Cm, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.oxml import parse_xml
    except ImportError:
        logger.warning(
            "[DocxPostProcessor] python-docx not installed – skipping post-processing. "
            "Install with: pip install python-docx"
        )
        return {"ok": True, "path": docx_path, "post_processed": False,
                "message": "python-docx not available, post-processing skipped"}

    path = Path(docx_path)
    if not path.exists():
        return {"ok": False, "error": f"DOCX file not found: {docx_path}"}

    try:
        doc = Document(str(path))
        changes_made = []

        # 1. Add professional header
        header_result = _add_header(doc, header_text or title)
        if header_result:
            changes_made.append(header_result)

        # 2. Add professional footer with page numbers and date
        footer_result = _add_footer(doc, footer_text, date)
        if footer_result:
            changes_made.append(footer_result)

        # 3. Ensure proper TOC field
        if include_toc:
            toc_result = _ensure_toc_field(doc)
            if toc_result:
                changes_made.append(toc_result)

        # 4. Remove duplicate titles (cover page title repeated in body)
        if remove_duplicate_titles:
            dup_result = _remove_duplicate_titles(doc)
            if dup_result:
                changes_made.append(dup_result)

        # Save the modified document
        doc.save(str(path))
        size_kb = round(path.stat().st_size / 1024, 1)

        logger.info(
            "[DocxPostProcessor] Post-processing complete: %s",
            ", ".join(changes_made) if changes_made else "no changes needed"
        )

        return {
            "ok": True,
            "path": str(path),
            "size_kb": size_kb,
            "post_processed": True,
            "changes": changes_made,
        }

    except Exception as exc:
        logger.exception("[DocxPostProcessor] Post-processing failed")
        return {"ok": False, "error": str(exc)}


def _add_header(doc, title: str) -> str:
    """Add a professional header with document title and bottom border.

    Returns a description of changes made, or empty string if no changes.
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    from docx.oxml import parse_xml

    if not title:
        return ""

    for section in doc.sections:
        header = section.header
        header.is_linked_to_previous = False

        # Clear existing content
        for p in header.paragraphs:
            p.clear()

        # Add header text
        para = header.paragraphs[0] if header.paragraphs else header.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.LEFT

        run = para.add_run(title)
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        run.font.name = "Calibri"

        # Add bottom border to header
        pPr = para._element.get_or_add_pPr()
        pBdr = parse_xml(
            '<w:pBdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '  <w:bottom w:val="single" w:sz="4" w:space="1" w:color="999999"/>'
            '</w:pBdr>'
        )
        pPr.append(pBdr)

    return "header added"


def _add_footer(doc, footer_text: str = "", date: str = "") -> str:
    """Add a professional footer with page numbers and optional date.

    Returns a description of changes made, or empty string if no changes.
    """
    from datetime import datetime
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    from docx.oxml import parse_xml

    if not date:
        date = format_date_de()

    for section in doc.sections:
        footer = section.footer
        footer.is_linked_to_previous = False

        # Clear existing content
        for p in footer.paragraphs:
            p.clear()

        para = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # Date text
        date_run = para.add_run(date)
        date_run.font.size = Pt(9)
        date_run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        date_run.font.name = "Calibri"

        # Separator
        sep_run = para.add_run("  |  ")
        sep_run.font.size = Pt(9)
        sep_run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

        # "Seite " prefix
        page_label = para.add_run("Seite ")
        page_label.font.size = Pt(9)
        page_label.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

        # PAGE field (auto-updating page number)
        fld_begin = parse_xml(
            '<w:fldChar w:fldCharType="begin" '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
        )
        fld_instr = parse_xml(
            '<w:instrText xml:space="preserve" '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            ' PAGE </w:instrText>'
        )
        fld_separate = parse_xml(
            '<w:fldChar w:fldCharType="separate" '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
        )
        fld_end = parse_xml(
            '<w:fldChar w:fldCharType="end" '
            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
        )

        # Create runs for the field
        run1 = para.add_run()
        run1._element.append(fld_begin)
        run2 = para.add_run()
        run2._element.append(fld_instr)
        run3 = para.add_run()
        run3._element.append(fld_separate)
        # Placeholder text shown before field updates
        placeholder = para.add_run("1")
        placeholder.font.size = Pt(9)
        placeholder.font.color.rgb = RGBColor(0x66, 0x66, 0x66)
        run4 = para.add_run()
        run4._element.append(fld_end)

        # Add top border to footer
        pPr = para._element.get_or_add_pPr()
        pBdr = parse_xml(
            '<w:pBdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '  <w:top w:val="single" w:sz="4" w:space="1" w:color="999999"/>'
            '</w:pBdr>'
        )
        pPr.append(pBdr)

    return "footer with date and page numbers added"


def _ensure_toc_field(doc) -> str:
    """Ensure the document has a proper TOC field.

    If a heading "Inhaltsverzeichnis" or "Table of Contents" exists without
    a proper TOC field, this inserts one. If no TOC heading exists at all,
    this does nothing (the document may not need one).

    Returns a description of changes made, or empty string if no changes.
    """
    from docx.shared import Pt, RGBColor
    from docx.oxml.ns import qn
    from docx.oxml import parse_xml

    toc_heading_idx = None
    toc_keywords = ["inhaltsverzeichnis", "table of contents", "toc", "verzeichnis"]

    for i, para in enumerate(doc.paragraphs):
        style_name = para.style.name.lower() if para.style else ""
        text = para.text.strip().lower()

        # Check if this is a TOC heading
        is_heading = "heading" in style_name or style_name in ("title",)
        if is_heading and any(kw in text for kw in toc_keywords):
            toc_heading_idx = i
            break

    if toc_heading_idx is None:
        # No TOC heading found - check if there's already a TOC field
        for para in doc.paragraphs:
            for run in para.runs:
                parent = run._element.getparent()
                if parent is not None:
                    fld_chars = parent.findall(qn('w:fldChar'))
                    instr_texts = parent.findall(qn('w:instrText'))
                    for instr in instr_texts:
                        if instr.text and 'TOC' in (instr.text or '').upper():
                            return ""  # TOC field already exists
        return ""  # No TOC heading found, don't add one

    # Check if there's already a TOC field after the heading
    para = doc.paragraphs[toc_heading_idx]
    # Look at the next few paragraphs for existing TOC field
    for j in range(toc_heading_idx + 1, min(toc_heading_idx + 5, len(doc.paragraphs))):
        next_para = doc.paragraphs[j]
        for run in next_para.runs:
            parent = run._element.getparent()
            if parent is not None:
                instr_texts = parent.findall(qn('w:instrText'))
                for instr in instr_texts:
                    if instr.text and 'TOC' in (instr.text or '').upper():
                        return ""  # TOC field already exists

    # Insert a TOC field after the heading
    # We need to add it as a new paragraph after the TOC heading
    toc_para = _insert_paragraph_after(para)

    # Build the TOC field XML
    fld_begin = parse_xml(
        '<w:fldChar w:fldCharType="begin" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
    )
    fld_instr = parse_xml(
        '<w:instrText xml:space="preserve" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        ' TOC \\o "1-3" \\h \\z \\u </w:instrText>'
    )
    fld_separate = parse_xml(
        '<w:fldChar w:fldCharType="separate" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
    )
    fld_end = parse_xml(
        '<w:fldChar w:fldCharType="end" '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"/>'
    )

    run1 = toc_para.add_run()
    run1._element.append(fld_begin)
    run2 = toc_para.add_run()
    run2._element.append(fld_instr)
    run3 = toc_para.add_run()
    run3._element.append(fld_separate)
    # Placeholder text (shown before field updates in Word)
    placeholder = toc_para.add_run("[Inhaltsverzeichnis – Rechtsklick → Feld aktualisieren]")
    placeholder.font.size = Pt(10)
    placeholder.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    placeholder.italic = True
    run4 = toc_para.add_run()
    run4._element.append(fld_end)

    return "TOC field inserted"


def _remove_duplicate_titles(doc) -> str:
    """Remove duplicate title/subtitle headings that appear both on cover and in body.

    Pandoc's cover page creates Title and Subtitle styles, but the Markdown
    content may also contain ## Title and ### Subtitle headings that duplicate
    the cover page. This removes the body duplicates.

    Returns a description of changes made, or empty string if no changes.
    """
    from docx.oxml.ns import qn

    # Collect title/subtitle from the cover page (Title/Subtitle styles)
    cover_titles = set()
    cover_end_idx = 0  # Track where cover page ends
    for i, para in enumerate(doc.paragraphs):
        style_name = para.style.name if para.style else ""
        text = para.text.strip()
        if style_name in ("Title", "Subtitle") and text:
            cover_titles.add(text)
            cover_end_idx = max(cover_end_idx, i)

    if not cover_titles:
        return ""

    # Find and remove duplicate headings AFTER the cover page
    # A heading is a duplicate if it has the same text as a Title/Subtitle
    # from the cover page AND it's a Heading style (not Title/Subtitle)
    elements_to_remove = []
    for i in range(cover_end_idx + 1, len(doc.paragraphs)):
        para = doc.paragraphs[i]
        style_name = para.style.name if para.style else ""
        text = para.text.strip()

        # Check if this is a heading that duplicates a cover page title
        if style_name.startswith("Heading") and text in cover_titles:
            elements_to_remove.append(para._element)

    for elem in elements_to_remove:
        elem.getparent().remove(elem)

    removed = len(elements_to_remove)
    if removed > 0:
        return f"removed {removed} duplicate title(s)"
    return ""


def _insert_paragraph_after(paragraph):
    """Insert a new paragraph after the given paragraph in the document.

    Returns the new paragraph object.
    """
    from docx.oxml import parse_xml
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph

    new_p = parse_xml(
        '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '</w:p>'
    )
    paragraph._element.addnext(new_p)

    # Return a Paragraph wrapper for the new element
    from docx.text.paragraph import Paragraph
    return Paragraph(new_p, paragraph._element.getparent())