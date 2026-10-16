from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Awaitable, Callable, TypeVar

from telethon import errors

T = TypeVar("T")


class RateLimiter:
    """Conservative per-account Telegram request limiter.

    The limiter intentionally favors reliability over speed. It spaces Telegram
    RPC calls, remembers server-requested cooldowns, and retries FloodWaitError
    instead of treating a temporary rate limit as a failed quiz.
    """

    def __init__(self, min_interval: float = 1.20, flood_extra: float = 2.0):
        self.min_interval = float(min_interval)
        self.flood_extra = float(flood_extra)
        self.last = defaultdict(float)
        self.blocked_until = defaultdict(float)
        self.lock = asyncio.Lock()
        self.flood_waits = 0
        self.flood_wait_seconds = 0

    async def wait(self, key: str = "global") -> None:
        key = str(key or "global")
        async with self.lock:
            now = time.monotonic()
            delay = max(
                self.min_interval - (now - self.last[key]),
                self.blocked_until[key] - now,
            )
            if delay > 0:
                await asyncio.sleep(delay)
            self.last[key] = time.monotonic()

    async def penalize(self, seconds: float, key: str = "global") -> None:
        key = str(key or "global")
        async with self.lock:
            seconds = max(0.0, float(seconds))
            self.flood_waits += 1
            self.flood_wait_seconds += int(seconds)
            until = time.monotonic() + seconds + self.flood_extra
            if until > self.blocked_until[key]:
                self.blocked_until[key] = until

    async def call(
        self,
        fn: Callable[[], Awaitable[T]],
        *,
        key: str = "global",
        retries: int = 5,
        on_flood: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> T:
        """Run an async Telegram RPC with spacing + FloodWait recovery.

        `fn` must create/execute one RPC. On FloodWait we wait for Telegram's
        requested duration plus a small safety margin and retry. The final
        FloodWait is re-raised so callers can stop cleanly rather than silently
        losing a quiz.
        """
        for attempt in range(1, int(retries) + 2):
            await self.wait(key)
            try:
                return await fn()
            except errors.FloodWaitError as exc:
                seconds = max(1, int(getattr(exc, "seconds", 1)))
                await self.penalize(seconds, key)
                if on_flood is not None:
                    try:
                        await on_flood(seconds, attempt)
                    except Exception:
                        pass
                if attempt > int(retries):
                    raise
                # penalize() already reserves the cooldown; wait() consumes it.
        raise RuntimeError("Telegram RPC retry loop ended unexpectedly")


# One limiter per process/account. The scanner and private-chat intake therefore
# cannot accidentally send vote RPCs at the same time.
GLOBAL_RATE_LIMITER = RateLimiter(min_interval=1.20, flood_extra=2.0)
# Voting is much more sensitive than ordinary reads. Keep it deliberately slow.
# This is ~20 votes/minute before Telegram has to intervene.
VOTE_RATE_LIMITER = RateLimiter(min_interval=3.0, flood_extra=3.0)
