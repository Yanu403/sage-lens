"""Intent router — classifies user queries using Gemma via Gemini API."""

from __future__ import annotations

import json
import logging
from openai import AsyncOpenAI

from config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_BASE_URL

log = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=GEMINI_API_KEY, base_url=GEMINI_BASE_URL)
    return _client


SYSTEM_PROMPT = """\
You are an intent classifier for a search assistant. Given a user query, classify it and produce an optimal search query if needed.

Respond in **valid JSON only** — no markdown, no explanation.

Schema:
{
  "intent": "search" | "reason" | "search_reason",
  "search_query": "<optimised web search query, or empty string if intent=reason>",
  "language": "<ISO 639-1 code: id, en, zh, ...>"
}

Guidelines:
- "search": the user needs real-time or factual web information (news, prices, events, definitions of recent things)
- "reason": the user needs pure reasoning, opinion, math, logic, or general knowledge that does NOT require live data
- "search_reason": the user needs web data AND analysis/synthesis on top of it
- search_query should be concise (3-8 words), optimised for web search engines
- Detect the user's language from the query text; default to "id" if unclear
"""


async def classify(query: str) -> dict:
    """Return {"intent": str, "search_query": str, "language": str}."""
    client = _get_client()
    try:
        resp = await client.chat.completions.create(
            model=GEMINI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        # Strip <thought>...</thought> blocks (Gemma thinking mode)
        import re
        raw = re.sub(r"<thought>.*?</thought>", "", raw, flags=re.DOTALL).strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(raw)
        # Validate keys
        intent = result.get("intent", "search")
        if intent not in ("search", "reason", "search_reason"):
            intent = "search"
        return {
            "intent": intent,
            "search_query": result.get("search_query", query),
            "language": result.get("language", "id"),
        }
    except Exception as e:
        log.warning("Router classification failed: %s — defaulting to search", e)
        return {"intent": "search", "search_query": query, "language": "id"}
