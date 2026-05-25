"""Synthesis — MiMo v2.5 Pro generates answers with inline citations."""

from __future__ import annotations

import asyncio
import logging
from openai import AsyncOpenAI

from config import MIMO_API_KEY, MIMO_MODEL, MIMO_BASE_URL

log = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

_MAX_RETRIES = 2
_RETRY_DELAY = 2.0


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


def _fix_citations(text: str) -> str:
    """Fix malformed citations from the model.

    Handles cases like:
    - 'Joko Widodo 15' → 'Joko Widodo [15]'
    - 'Presiden 4' → 'Presiden [4]'
    - 'text 1,2,3' → 'text [1],[2],[3]'
    Does NOT touch already-correct '[15]' or numbers in normal sentences.
    """
    import re

    def _wrap_if_citation(match: re.Match) -> str:
        """Wrap matched number in brackets if it looks like a citation."""
        prefix = match.group(1)  # character before the space+number
        num = int(match.group(2))
        # Only wrap if preceded by a letter (not digit, not bracket)
        if prefix.isalpha() and num <= 30:
            return f'{prefix} [{num}]'
        return match.group(0)

    # Fix bare numbers after words: "Widodo 15." → "Widodo [15]."
    # Captures: (char before space)(1-2 digit number)(boundary)
    text = re.sub(
        r'([a-zA-Z]) (\d{1,2})(?=[\s,.\);:。、]|$)',
        _wrap_if_citation,
        text,
    )

    # Fix comma-separated bare citations: "sekarang 1,2,3" → "sekarang [1],[2],[3]"
    # Step 1: first number after word
    text = re.sub(
        r'([a-zA-Z\]\s])(\d{1,2})(?=,\d)',
        lambda m: f'{m.group(1)}[{m.group(2)}]' if int(m.group(2)) <= 30 else m.group(0),
        text,
    )
    # Step 2: numbers after commas in citation chains
    text = re.sub(
        r'(,)(\d{1,2})(?=[\s,.\);:。、]|$)',
        lambda m: f'{m.group(1)}[{m.group(2)}]' if int(m.group(2)) <= 30 else m.group(0),
        text,
    )

    # Fix 'text [1] [2]' → 'text [1][2]' (remove space between consecutive citations)
    text = re.sub(r'\]\s+\[', '][', text)

    return text


async def _call_mimo(messages: list[dict], extra_body: dict | None = None) -> str:
    """Single MiMo API call."""
    client = _get_client()
    kwargs = dict(
        model=MIMO_MODEL,
        messages=messages,
        temperature=0.3,
        max_tokens=2048,
    )
    if extra_body:
        kwargs["extra_body"] = extra_body
    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content.strip()


async def synthesize(
    query: str,
    sources: list[dict] | None = None,
    language: str = "id",
) -> str:
    """Generate an answer using MiMo with retry logic.

    If sources are provided, the answer will include inline citations [1], [2], etc.
    If no sources, the model reasons from its own knowledge.
    """
    if sources:
        messages = _build_search_prompt(language, query, sources)
    else:
        messages = _build_reason_prompt(language, query)

    # Detect content-filter / safety rejections from the model
    _SAFETY_PATTERNS = [
        "high risk",
        "rejected",
        "safety",
        "harmful",
        "inappropriate",
        "blocked",
        "refused",
    ]

    last_error = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            answer = await _call_mimo(messages)

            # Check if the model returned a safety rejection instead of an answer
            answer_lower = answer.lower()
            if any(pat in answer_lower for pat in _SAFETY_PATTERNS) and len(answer) < 200:
                log.warning("MiMo returned safety rejection: %s", answer[:100])
                return (
                    "⚠️ Model AI menolak menjawab pertanyaan ini karena dianggap sensitif. "
                    "Coba rephrase pertanyaanmu atau gunakan kata yang lebih netral."
                )

            return _fix_citations(answer)
        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # If thinking mode error, try with thinking disabled
            if "reasoning_content" in error_str or "thinking" in error_str:
                log.warning("MiMo thinking mode error, retrying with thinking disabled")
                try:
                    return await _call_mimo(messages, extra_body={"thinking": {"type": "disabled"}})
                except Exception as e2:
                    last_error = e2

            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAY * (attempt + 1)
                log.warning(
                    "MiMo attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES + 1, e, delay,
                )
                await asyncio.sleep(delay)

    log.error("MiMo synthesis failed after %d attempts: %s", _MAX_RETRIES + 1, last_error)
    raise last_error
