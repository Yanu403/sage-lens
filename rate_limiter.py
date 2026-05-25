"""Per-user sliding-window rate limiter — SQLite-backed with in-memory fallback."""

from __future__ import annotations

import logging
import time

import aiosqlite

from config import RATE_LIMIT_PER_HOUR, CACHE_DB_PATH

log = logging.getLogger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS rate_limits (
    user_id     INTEGER NOT NULL,
    timestamp   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate_user ON rate_limits(user_id);
CREATE INDEX IF NOT EXISTS idx_rate_ts ON rate_limits(timestamp);
"""


class RateLimiter:
    """SQLite-backed sliding-window rate limiter.

    Falls back to in-memory if DB is unavailable.
    """

    def __init__(self):
        self._db: aiosqlite.Connection | None = None
        self._memory: dict[int, list[float]] = {}  # fallback

    async def init(self, db_path: str | None = None) -> None:
        try:
            self._db = await aiosqlite.connect(str(db_path or CACHE_DB_PATH))
            await self._db.executescript(_CREATE_SQL)
            await self._db.commit()
            log.info("Rate limiter: SQLite backend at %s", db_path or CACHE_DB_PATH)
        except Exception as e:
            log.warning("Rate limiter: SQLite init failed (%s), using in-memory fallback", e)
            self._db = None

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def check(
        self,
        user_id: int,
        limit: int | None = None,
        window: int = 3600,
    ) -> tuple[bool, int]:
        """Return (allowed, remaining) for the given user."""
        limit = limit or RATE_LIMIT_PER_HOUR

        if self._db:
            return await self._check_db(user_id, limit, window)
        return self._check_memory(user_id, limit, window)

    async def cleanup(self, window: int = 3600) -> int:
        """Remove expired entries. Returns count of removed rows."""
        if not self._db:
            return 0
        cutoff = time.time() - window
        async with self._db.execute(
            "DELETE FROM rate_limits WHERE timestamp < ?", (cutoff,)
        ) as cur:
            removed = cur.rowcount
        await self._db.commit()
        return removed

    # ── SQLite backend ───────────────────────────────────

    async def _check_db(
        self, user_id: int, limit: int, window: int
    ) -> tuple[bool, int]:
        cutoff = time.time() - window

        # Prune old entries for this user
        await self._db.execute(
            "DELETE FROM rate_limits WHERE user_id = ? AND timestamp < ?",
            (user_id, cutoff),
        )

        # Count current window
        async with self._db.execute(
            "SELECT COUNT(*) FROM rate_limits WHERE user_id = ?",
            (user_id,),
        ) as cur:
            count = (await cur.fetchone())[0]

        remaining = limit - count
        if remaining <= 0:
            await self._db.commit()
            return False, 0

        # Record this request
        await self._db.execute(
            "INSERT INTO rate_limits (user_id, timestamp) VALUES (?, ?)",
            (user_id, time.time()),
        )
        await self._db.commit()
        return True, remaining - 1

    # ── In-memory fallback ───────────────────────────────

    def _check_memory(
        self, user_id: int, limit: int, window: int
    ) -> tuple[bool, int]:
        now = time.time()
        bucket = self._memory.setdefault(user_id, [])
        bucket[:] = [t for t in bucket if now - t < window]

        remaining = limit - len(bucket)
        if remaining <= 0:
            return False, 0

        bucket.append(now)
        return True, remaining - 1
