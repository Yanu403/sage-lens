"""Web search via Tavily + content extraction via trafilatura."""

from __future__ import annotations

import asyncio
import logging

from tavily import AsyncTavilyClient
import trafilatura
import httpx

from config import TAVILY_API_KEY, MAX_SOURCES, MAX_CONTEXT_CHARS

log = logging.getLogger(__name__)

_client: AsyncTavilyClient | None = None

# Per-source fetch timeout (seconds)
_FETCH_TIMEOUT = 8.0
# Retry config for Tavily
_MAX_RETRIES = 2
_RETRY_DELAY = 1.5


def _get_client() -> AsyncTavilyClient:
    global _client
    if _client is None:
        _client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
    return _client


async def search(query: str, max_results: int | None = None) -> list[dict]:
    """Search the web via Tavily with retry on transient failures.

    Returns list of dicts:
        [{"title": str, "url": str, "snippet": str}, ...]
    """
    max_results = max_results or MAX_SOURCES
    client = _get_client()

    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.search(
                query=query,
                max_results=max_results,
                search_depth="advanced",
                include_raw_content=False,
            )
            results = []
            for item in resp.get("results", []):
                results.append({
                    "title": item.get("title", "Untitled"),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                })
            return results[:max_results]

        except Exception as e:
            if attempt < _MAX_RETRIES:
                delay = _RETRY_DELAY * (attempt + 1)
                log.warning(
                    "Tavily search attempt %d/%d failed: %s — retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES + 1, e, delay,
                )
                await asyncio.sleep(delay)
            else:
                log.error("Tavily search failed after %d attempts: %s", _MAX_RETRIES + 1, e)
                return []


async def fetch_content(url: str, timeout: float = _FETCH_TIMEOUT) -> Optional[str]:
    """Fetch a URL and extract main text content via trafilatura.

    Raises asyncio.TimeoutError if the fetch exceeds `timeout`.
    """
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "SageLens/1.0"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text
    except Exception as e:
        log.debug("Fetch failed for %s: %s", _truncate(url, 60), e)
        return None

    # trafilatura.extract is CPU-bound; run in executor to not block event loop
    loop = asyncio.get_running_loop()
    text = await loop.run_in_executor(
        None,
        lambda: trafilatura.extract(html, include_comments=False, include_tables=False),
    )
    return text


async def _fetch_with_timeout(url: str, budget: int) -> dict:
    """Fetch a single source with timeout guard. Returns {title, url, content}."""
    snippet = ""
    try:
        full = await asyncio.wait_for(fetch_content(url), timeout=_FETCH_TIMEOUT)
        if full and len(full) > 50:
            snippet = full
    except asyncio.TimeoutError:
        log.debug("Timeout fetching %s after %.0fs", _truncate(url, 60), _FETCH_TIMEOUT)
    except Exception as e:
        log.debug("Error fetching %s: %s", _truncate(url, 60), e)

    # Truncate to budget
    if len(snippet) > budget:
        snippet = snippet[:budget].rsplit(" ", 1)[0] + " [...]"

    return {"content": snippet}


async def enrich_sources(sources: list[dict]) -> list[dict]:
    """Fetch full content for each source concurrently with per-source timeout.

    Uses asyncio.gather so one slow source doesn't block the rest.
    """
    if not sources:
        return sources

    per_source_budget = MAX_CONTEXT_CHARS // len(sources)

    # Fetch all concurrently — each has its own timeout
    tasks = [
        _fetch_with_timeout(src.get("url", ""), per_source_budget)
        for src in sources
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched = []
    for src, result in zip(sources, results):
        if isinstance(result, Exception):
            log.debug("Enrich failed for %s: %s", _truncate(src.get("url", ""), 60), result)
            enriched.append(src)
        else:
            content = result.get("content", "")
            enriched.append({
                **src,
                "content": content or src.get("snippet", ""),
            })

    return enriched


def _truncate(s: str, max_len: int) -> str:
    return s[:max_len] + "..." if len(s) > max_len else s
