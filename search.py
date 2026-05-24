"""Web search via Tavily + content extraction via trafilatura."""

from __future__ import annotations

import logging
from typing import Optional

from tavily import AsyncTavilyClient
import trafilatura

from config import TAVILY_API_KEY, MAX_SOURCES, MAX_CONTEXT_CHARS

log = logging.getLogger(__name__)

_client: AsyncTavilyClient | None = None


def _get_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        _client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
    return _client


async def search(query: str, max_results: int | None = None) -> list[dict]:
    """Search the web via Tavily.

    Returns list of dicts:
        [{"title": str, "url": str, "snippet": str, "content": str}, ...]
    """
    max_results = max_results or MAX_SOURCES
    client = _get_client()
    try:
        resp = await client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            include_raw_content=False,
        )
    except Exception as e:
        log.error("Tavily search failed: %s", e)
        return []

    results = []
    for item in resp.get("results", []):
        results.append({
            "title": item.get("title", "Untitled"),
            "url": item.get("url", ""),
            "snippet": item.get("content", ""),
        })

    return results[:max_results]


async def fetch_content(url: str, timeout: float = 10.0) -> Optional[str]:
    """Fetch a URL and extract main text content via trafilatura."""
    import httpx

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "MiniSearchAgent/1.0"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        log.debug("Fetch failed for %s: %s", url, e)
        return None

    text = trafilatura.extract(html, include_comments=False, include_tables=False)
    return text


async def enrich_sources(sources: list[dict]) -> list[dict]:
    """Fetch full content for each source, respecting context budget.

    Returns the same list with 'content' field populated.
    """
    if not sources:
        return sources

    per_source_budget = MAX_CONTEXT_CHARS // len(sources)

    enriched = []
    for src in sources:
        url = src.get("url", "")
        content = src.get("snippet", "")

        # Try to fetch full content
        full = await fetch_content(url)
        if full and len(full) > 50:
            content = full

        # Truncate to budget
        if len(content) > per_source_budget:
            content = content[:per_source_budget].rsplit(" ", 1)[0] + " [...]"

        enriched.append({
            **src,
            "content": content,
        })

    return enriched
