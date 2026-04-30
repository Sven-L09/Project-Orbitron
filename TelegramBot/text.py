from __future__ import annotations


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
