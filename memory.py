"""In-memory conversation memory with TTL expiry per user."""

from __future__ import annotations

import asyncio
import logging
import time

log = logging.getLogger(__name__)

# Default config
_MAX_HISTORY = 10        # max messages per user (user+assistant pairs)
_TTL_SECONDS = 600       # 10 minutes idle → forget


class ConversationMemory:
    """Per-user conversation history stored in memory.

    Each entry is {"role": "user"|"assistant", "content": str, "ts": float}.
    History auto-expires after TTL_SECONDS of inactivity.
    """

    def __init__(
        self,
        max_history: int = _MAX_HISTORY,
        ttl: int = _TTL_SECONDS,
    ):
        self._max_history = max_history
        self._ttl = ttl
        self._store: dict[int, list[dict]] = {}

    def get_history(self, user_id: int) -> list[dict]:
        """Return conversation history for a user (OpenAI messages format).

        Returns empty list if expired or not found. Auto-prunes expired.
        """
        if user_id not in self._store:
            return []

        history = self._store[user_id]
        if not history:
            return []

        # Check if expired (last message older than TTL)
        if time.time() - history[-1]["ts"] > self._ttl:
            del self._store[user_id]
            return []

        # Return in OpenAI format (strip internal 'ts' field)
        return [{"role": m["role"], "content": m["content"]} for m in history]

    def add_user_message(self, user_id: int, content: str) -> None:
        """Record a user message."""
        self._ensure_user(user_id)
        self._store[user_id].append({
            "role": "user",
            "content": content,
            "ts": time.time(),
        })
        self._trim(user_id)

    def add_assistant_message(self, user_id: int, content: str) -> None:
        """Record an assistant response."""
        self._ensure_user(user_id)
        self._store[user_id].append({
            "role": "assistant",
            "content": content,
            "ts": time.time(),
        })
        self._trim(user_id)

    def clear(self, user_id: int) -> None:
        """Clear history for a user."""
        self._store.pop(user_id, None)

    def _ensure_user(self, user_id: int) -> None:
        if user_id not in self._store:
            self._store[user_id] = []

    def _trim(self, user_id: int) -> None:
        """Keep only the last N messages (pairs)."""
        history = self._store[user_id]
        max_messages = self._max_history * 2  # user + assistant pairs
        if len(history) > max_messages:
            self._store[user_id] = history[-max_messages:]

    async def cleanup_loop(self) -> None:
        """Background task: prune expired conversations every 60s."""
        while True:
            await asyncio.sleep(60)
            now = time.time()
            expired = [
                uid for uid, msgs in self._store.items()
                if msgs and now - msgs[-1]["ts"] > self._ttl
            ]
            for uid in expired:
                del self._store[uid]
            if expired:
                log.debug("Conversation cleanup: %d expired", len(expired))
