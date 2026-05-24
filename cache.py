"""Async SQLite cache layer with TTL and LRU eviction."""

from __future__ import annotations

import hashlib
import json
import time
from typing import Optional

import aiosqlite

from config import CACHE_DB_PATH, INTENT_TTL, CACHE_TTL_HOURS

MAX_ENTRIES = 10_000

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS cache (
    query_hash  TEXT PRIMARY KEY,
    query_text  TEXT NOT NULL,
    response    TEXT NOT NULL,
    sources_json TEXT DEFAULT '[]',
    intent      TEXT DEFAULT 'search',
    created_at  REAL NOT NULL,
    hit_count   INTEGER DEFAULT 0,
    ttl_hours   INTEGER DEFAULT 6
);
"""


def _normalise(query: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    import re
    q = query.lower().strip()
    q = re.sub(r"[^\w\s]", "", q)
    return re.sub(r"\s+", " ", q)


def _hash(query: str) -> str:
    return hashlib.sha256(_normalise(query).encode()).hexdigest()


class Cache:
    """Thin async wrapper around SQLite for query caching."""

    def __init__(self, db_path: str | None = None):
        self._path = str(db_path or CACHE_DB_PATH)
        self._db: Optional[aiosqlite.Connection] = None

    async def init(self) -> None:
        self._db = await aiosqlite.connect(self._path)
        await self._db.execute(_CREATE_SQL)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def get(self, query: str) -> Optional[dict]:
        """Return cached response dict or None if expired / missing."""
        h = _hash(query)
        async with self._db.execute(
            "SELECT response, sources_json, intent, created_at, ttl_hours, hit_count "
            "FROM cache WHERE query_hash = ?",
            (h,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None

        response, sources_json, intent, created_at, ttl, hits = row
        if time.time() - created_at > ttl * 3600:
            await self._evict(h)
            return None

        # bump hit count
        await self._db.execute(
            "UPDATE cache SET hit_count = ? WHERE query_hash = ?",
            (hits + 1, h),
        )
        await self._db.commit()

        return {
            "response": response,
            "sources": json.loads(sources_json),
            "intent": intent,
            "from_cache": True,
        }

    async def put(
        self,
        query: str,
        response: str,
        sources: list[dict],
        intent: str = "search",
    ) -> None:
        h = _hash(query)
        ttl = INTENT_TTL.get(intent, CACHE_TTL_HOURS)
        await self._evict_if_full()
        await self._db.execute(
            "INSERT OR REPLACE INTO cache "
            "(query_hash, query_text, response, sources_json, intent, created_at, ttl_hours) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (h, _normalise(query), response, json.dumps(sources), intent, time.time(), ttl),
        )
        await self._db.commit()

    # ── internal ─────────────────────────────────────────

    async def _evict(self, query_hash: str) -> None:
        await self._db.execute("DELETE FROM cache WHERE query_hash = ?", (query_hash,))
        await self._db.commit()

    async def _evict_if_full(self) -> None:
        async with self._db.execute("SELECT COUNT(*) FROM cache") as cur:
            count = (await cur.fetchone())[0]
        if count >= MAX_ENTRIES:
            await self._db.execute(
                "DELETE FROM cache WHERE query_hash IN "
                "(SELECT query_hash FROM cache ORDER BY hit_count ASC, created_at ASC LIMIT ?)",
                (max(1, count - MAX_ENTRIES + 100),),
            )
            await self._db.commit()
