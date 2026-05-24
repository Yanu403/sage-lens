"""Per-user sliding-window rate limiter (in-memory)."""

from __future__ import annotations

import time
from config import RATE_LIMIT_PER_HOUR

_windows: dict[int, list[float]] = {}


def check_rate_limit(
    user_id: int,
    limit: int | None = None,
    window: int = 3600,
) -> tuple[bool, int]:
    """Return (allowed, remaining) for the given user.

    allowed   — True if the request is within the limit
    remaining — how many requests are left in the window
    """
    limit = limit or RATE_LIMIT_PER_HOUR
    now = time.time()
    bucket = _windows.setdefault(user_id, [])
    # prune old entries
    bucket[:] = [t for t in bucket if now - t < window]

    remaining = limit - len(bucket)
    if remaining <= 0:
        return False, 0

    bucket.append(now)
    return True, remaining - 1
