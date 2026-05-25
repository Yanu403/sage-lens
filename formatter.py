"""Telegram message formatter — turns synthesis output into clean Telegram messages."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

log = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 4096
SAFE_LENGTH = 3800  # leave room for sources footer


def format_response(answer: str, sources: list[dict] | None = None) -> list[str]:
    """Format the answer + sources into one or more Telegram-ready messages.

    Returns a list of message strings (split if answer is too long).
    `sources` defaults to empty list if None.
    """
    sources = sources or []

    full = answer.strip()
    if sources:
        footer = _build_sources_footer(sources)
        full = f"{full}\n\n{footer}"

    # Split if too long
    if len(full) <= MAX_MESSAGE_LENGTH:
        return [full]

    # Split answer into chunks, attach footer to last chunk
    chunks = _split_text(answer.strip(), SAFE_LENGTH)
    messages = list(chunks[:-1]) if len(chunks) > 1 else []
    last = chunks[-1] if chunks else answer[:SAFE_LENGTH]
    if sources:
        last = f"{last}\n\n{_build_sources_footer(sources)}"
    if len(last) > MAX_MESSAGE_LENGTH:
        last = last[: MAX_MESSAGE_LENGTH - 50] + "\n\n[...] 🔗 Lihat sumber di bawah"
    messages.append(last)
    return messages


def _build_sources_footer(sources: list[dict]) -> str:
    """Build the 📎 Sources section."""
    lines = ["📎 *Sumber:*"]
    seen_urls: set[str] = set()
    for i, src in enumerate(sources, 1):
        url = src.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = src.get("title", "Link")
        domain = _extract_domain(url)
        if len(title) > 60:
            title = title[:57] + "..."
        lines.append(f"{i}. {title} — {domain}")
    return "\n".join(lines)


def _extract_domain(url: str) -> str:
    """Extract domain from URL."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return url


def _split_text(text: str, max_len: int) -> list[str]:
    """Split text into chunks at paragraph/sentence boundaries."""
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Try to split at paragraph boundary
        split_at = remaining.rfind("\n\n", 0, max_len)
        if split_at < max_len // 2:
            # Try sentence boundary
            split_at = remaining.rfind(". ", 0, max_len)
        if split_at < max_len // 2:
            # Hard split
            split_at = max_len

        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()

    return chunks
