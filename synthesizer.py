"""Synthesis — MiMo v2.5 Pro generates answers with inline citations."""

from __future__ import annotations

import logging
from openai import AsyncOpenAI

from config import MIMO_API_KEY, MIMO_MODEL, MIMO_BASE_URL

log = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=MIMO_API_KEY, base_url=MIMO_BASE_URL)
    return _client


SEARCH_SYSTEM_PROMPT = """\
You are a precise search assistant. Answer the user's question using ONLY the provided sources.

RULES:
- Answer in the user's detected language ({language})
- Cite sources inline using [1], [2], etc. — match the source numbers provided
- If sources conflict, mention the disagreement briefly
- If no source has relevant info, say you couldn't find a reliable answer
- Be concise but thorough — 2-4 paragraphs maximum
- Use **bold** for key terms on first mention
- End with a brief summary sentence if the answer is complex
- Do NOT fabricate information not present in the sources
- Do NOT include a sources list in your answer — the system appends it automatically
"""


REASON_SYSTEM_PROMPT = """\
You are a helpful AI assistant. Answer the user's question thoughtfully and accurately.

RULES:
- Answer in the user's detected language ({language})
- Be concise but thorough — 2-4 paragraphs maximum
- Use **bold** for key terms on first mention
- Use bullet points for lists
- If the question is ambiguous, address the most likely interpretation
"""


def _build_search_prompt(language: str, query: str, sources: list[dict]) -> list[dict]:
    """Build messages for search+synthesis."""
    system = SEARCH_SYSTEM_PROMPT.format(language=language)

    source_blocks = []
    for i, src in enumerate(sources, 1):
        source_blocks.append(
            f"[{i}] {src['title']} — {src['url']}\n{src.get('content', src.get('snippet', ''))}"
        )

    user_content = (
        f"Question: {query}\n\n"
        f"Sources:\n" + "\n\n".join(source_blocks)
    )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def _build_reason_prompt(language: str, query: str) -> list[dict]:
    """Build messages for reasoning-only."""
    system = REASON_SYSTEM_PROMPT.format(language=language)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": query},
    ]


async def synthesize(
    query: str,
    sources: list[dict] | None = None,
    language: str = "id",
) -> str:
    """Generate an answer using MiMo.

    If sources are provided, the answer will include inline citations [1], [2], etc.
    If no sources, the model reasons from its own knowledge.
    """
    client = _get_client()

    if sources:
        messages = _build_search_prompt(language, query, sources)
    else:
        messages = _build_reason_prompt(language, query)

    try:
        resp = await client.chat.completions.create(
            model=MIMO_MODEL,
            messages=messages,
            temperature=0.3,
            max_tokens=2048,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error("MiMo synthesis failed: %s", e)
        # Fallback: try without thinking mode params
        try:
            resp = await client.chat.completions.create(
                model=MIMO_MODEL,
                messages=messages,
                temperature=0.3,
                max_tokens=2048,
                extra_body={"thinking": {"type": "disabled"}},
            )
            return resp.choices[0].message.content.strip()
        except Exception as e2:
            log.error("MiMo fallback also failed: %s", e2)
            raise
