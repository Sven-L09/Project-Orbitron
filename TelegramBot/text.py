from __future__ import annotations

import re


def split_telegram_text(text: str, *, limit: int = 4000) -> list[str]:
    """Telegram sendMessage max is ~4096 chars; keep a buffer."""
    if not text:
        return [""]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]

    if remaining:
        chunks.append(remaining)

    return chunks


def escape_markdown_v2(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2 formatting.

    Telegram MarkdownV2 requires escaping these characters: _ * [ ] ( ) ~ ` > # + - = | { } . !
    """
    special_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{c}" if c in special_chars else c for c in text)


def format_markdown_v2(text: str) -> str:
    """Convert plain text with common formatting to Telegram MarkdownV2.

    Converts:
    - **bold** → *bold*
    - *italic* → _italic_
    - `code` → `code`
    - ```code blocks``` → ```code blocks```
    - Bullet lines starting with - or * → properly formatted
    - Headers with # → bold text

    Then escapes all remaining special characters for MarkdownV2.
    """
    # First, protect code blocks and inline code from escaping
    code_blocks: list[str] = []
    inline_codes: list[str] = []

    # Protect fenced code blocks (```)
    def save_code_block(m: re.Match) -> str:
        code_blocks.append(m.group(0))
        return f"__CODE_BLOCK_{len(code_blocks) - 1}__"

    text = re.sub(r"```[\s\S]*?```", save_code_block, text)

    # Protect inline code (`)
    def save_inline_code(m: re.Match) -> str:
        inline_codes.append(m.group(0))
        return f"__INLINE_CODE_{len(inline_codes) - 1}__"

    text = re.sub(r"`[^`]+`", save_inline_code, text)

    # Convert **bold** to *bold* (Telegram MarkdownV2 bold)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)

    # Convert *italic* to _italic_ (Telegram MarkdownV2 italic)
    # But not if it's a bullet point (starts of lines)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"_\1_", text)

    # Convert headers (# ) to bold
    def format_header(m: re.Match) -> str:
        level = len(m.group(1))
        content = m.group(2).strip()
        return f"*{content}*"

    text = re.sub(r"^(#{1,3})\s+(.+)$", format_header, text, flags=re.MULTILINE)

    # Escape remaining special characters for MarkdownV2
    text = escape_markdown_v2(text)

    # Restore code blocks and inline code (they were protected from escaping)
    for i, block in enumerate(code_blocks):
        # Escape content inside code blocks too, but preserve the ``` delimiters
        text = text.replace(f"__CODE\\_BLOCK\\_{i}__", block)

    for i, code in enumerate(inline_codes):
        text = text.replace(f"__INLINE\\_CODE\\_{i}__", code)

    return text
