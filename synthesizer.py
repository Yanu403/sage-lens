"""Synthesis — LLM generates answers with inline citations.

Provider-agnostic: works with any OpenAI-compatible API
(MiMo, GPT, DeepSeek, Kimi, Claude via OpenRouter, Gemini, etc.)
"""

from __future__ import annotations

import asyncio
import logging
import re

from openai import (
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
    APITimeoutError,
    APIConnectionError,
)

from config import SYNTHESIS_API_KEY, SYNTHESIS_MODEL, SYNTHESIS_BASE_URL

log = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None

_MAX_RETRIES = 2
_RETRY_DELAY = 2.0

# Safety rejection patterns
_SAFETY_PATTERNS = [
    "high risk",
    "rejected",
    "safety",
    "harmful",
    "inappropriate",
    "blocked",
    "refused",
]


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=SYNTHESIS_API_KEY, base_url=SYNTHESIS_BASE_URL)
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


FOLLOWUP_SYSTEM_PROMPT = """\
You are a helpful AI assistant engaged in a conversation. The user may ask follow-up questions 
based on previous messages. Use the conversation context to understand references like 
"it", "that", "how about", "elaborate", etc.

RULES:
- Answer in the user's detected language ({language})
- If the user refers to something from earlier in the conversation, use that context
- If the reference is unclear, ask for clarification
- Be concise but thorough — 2-4 paragraphs maximum
- Use **bold** for key terms on first mention
"""


def _build_search_messages(
    language: str,
    query: str,
    sources: list[dict],
    history: list[dict] | None = None,
) -> list[dict]:
    """Build messages for search+synthesis, with optional conversation history."""
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

    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_content})
    return messages


def _build_reason_messages(
    language: str,
    query: str,
    history: list[dict] | None = None,
) -> list[dict]:
    """Build messages for reasoning-only, with optional conversation history."""
    # If there's history, use the follow-up prompt; otherwise use basic reason prompt
    if history:
        system = FOLLOWUP_SYSTEM_PROMPT.format(language=language)
    else:
        system = REASON_SYSTEM_PROMPT.format(language=language)

    messages = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": query})
    return messages


def _fix_citations(text: str) -> str:
    """Fix malformed citations from the model.

    Handles cases like:
    - 'Joko Widodo 15' → 'Joko Widodo [15]'
    - 'Presiden 4' → 'Presiden [4]'
    - 'text 1,2,3' → 'text [1],[2],[3]'
    Does NOT touch already-correct '[15]' or numbers in normal sentences.
    """

    def _wrap_if_citation(match: re.Match) -> str:
        prefix = match.group(1)
        num = int(match.group(2))
        if prefix.isalpha() and num <= 30:
            return f'{prefix} [{num}]'
        return match.group(0)

    # Fix bare numbers after words
    text = re.sub(
        r'([a-zA-Z]) (\d{1,2})(?=[\s,.\);:。、]|$)',
        _wrap_if_citation,
        text,
    )

    # Fix comma-separated bare citations
    text = re.sub(
        r'([a-zA-Z\]\s])(\d{1,2})(?=,\d)',
        lambda m: f'{m.group(1)}[{m.group(2)}]' if int(m.group(2)) <= 30 else m.group(0),
        text,
    )
    text = re.sub(
        r'(,)(\d{1,2})(?=[\s,.\);:。、]|$)',
        lambda m: f'{m.group(1)}[{m.group(2)}]' if int(m.group(2)) <= 30 else m.group(0),
        text,
    )

    # Remove space between consecutive citations
    text = re.sub(r'\]\s+\[', '][', text)

    return text


async def _call_llm(messages: list[dict], extra_body: dict | None = None) -> str:
    """Single LLM API call."""
    client = _get_client()
    kwargs = dict(
        model=SYNTHESIS_MODEL,
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
    history: list[dict] | None = None,
) -> str:
    """Generate an answer using the configured LLM with retry logic.

    Args:
        query: The user's question
        sources: Optional list of web sources for citation
        language: ISO language code
        history: Optional conversation history (OpenAI messages format)

    If sources are provided, the answer will include inline citations [1], [2], etc.
    If no sources, the model reasons from its own knowledge.
    """
    if sources:
        messages = _build_search_messages(language, query, sources, history)
    else:
        messages = _build_reason_messages(language, query, history)

    last_error = None

    for attempt in range(_MAX_RETRIES + 1):
        try:
            answer = await _call_llm(messages)

            # Check for safety rejection
            answer_lower = answer.lower()
            if any(pat in answer_lower for pat in _SAFETY_PATTERNS) and len(answer) < 200:
                log.warning("LLM returned safety rejection: %s", answer[:100])
                return (
                    "⚠️ Model AI menolak menjawab pertanyaan ini karena dianggap sensitif. "
                    "Coba rephrase pertanyaanmu atau gunakan kata yang lebih netral."
                )

            return _fix_citations(answer)

        except (AuthenticationError, RateLimitError) as e:
            # Don't retry auth or rate limit errors
            raise

        except (APITimeoutError, APIConnectionError) as e:
            last_error = e
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAY * (attempt + 1)
                log.warning(
                    "LLM attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES + 1, e, delay,
                )
                await asyncio.sleep(delay)

        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # MiMo-specific: thinking mode error → retry with thinking disabled
            if "reasoning_content" in error_str or "thinking" in error_str:
                log.warning("LLM thinking mode error, retrying with thinking disabled")
                try:
                    return _fix_citations(
                        await _call_llm(messages, extra_body={"thinking": {"type": "disabled"}})
                    )
                except Exception as e2:
                    last_error = e2

            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAY * (attempt + 1)
                log.warning(
                    "LLM attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES + 1, e, delay,
                )
                await asyncio.sleep(delay)

    log.error("LLM synthesis failed after %d attempts: %s", _MAX_RETRIES + 1, last_error)
    raise last_error
