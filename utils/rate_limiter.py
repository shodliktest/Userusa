from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from contextvars import ContextVar
from typing import Awaitable, Callable, TypeVar

from telethon import errors

T = TypeVar("T")

# FloodWait, SlowMode and the generic 420 FloodError all carry `.seconds`.
FLOOD_ERRORS = tuple(
    c for c in (
        getattr(errors, "FloodWaitError", None),
        getattr(errors, "FloodError", None),
        getattr(errors, "SlowModeWaitError", None),
    ) if c is not None
)
# Short network hiccups / server-side timeouts: retried with a growing pause.
TRANSIENT_ERRORS = tuple(
    c for c in (
        ConnectionError,
        TimeoutError,
        asyncio.TimeoutError,
        getattr(errors, "ServerError", None),
        getattr(errors, "TimedOutError", None),
    ) if c is not None
)


class StopRequested(BaseException):
    """Raised while waiting if the user pressed STOP.

    Derives from BaseException on purpose so that the many broad
    `except Exception` blocks in the scanner cannot swallow it.
    """


class Hooks:
    """Per-scan callbacks (carried by a ContextVar, so private chats are unaffected)."""

    def __init__(self, stop=None, on_wait=None, on_resume=None):
        self.stop = stop
        self.on_wait = on_wait
        self.on_resume = on_resume


HOOKS: ContextVar = ContextVar("rate_limit_hooks", default=None)


def _notify(name: str, *args) -> None:
    hooks = HOOKS.get()
    cb = getattr(hooks, name, None) if hooks else None
    if cb:
        try:
            cb(*args)
        except Exception:
            pass


notify_hooks = _notify


async def interruptible_sleep(delay: float) -> None:
    """Sleep in 1-second slices so STOP is honoured even during a long FloodWait."""
    end = time.monotonic() + max(0.0, float(delay))
    while True:
        hooks = HOOKS.get()
        if hooks and hooks.stop and hooks.stop():
            raise StopRequested()
        left = end - time.monotonic()
        if left <= 0:
            return
        await asyncio.sleep(min(1.0, left))


class RateLimiter:
    """Conservative per-account Telegram request limiter.

    Spaces Telegram RPC calls, remembers server-requested cooldowns and, when
    Telegram answers with a FloodWait of ANY length, waits it out and retries
    the same call - a rate limit never turns into a lost quiz. The wait can be
    interrupted with STOP and is reported through the per-scan hooks.
    """

    def __init__(self, min_interval: float = 1.20, flood_extra: float = 2.0,
                 max_flood_wait: float = 24 * 3600):
        self.min_interval = float(min_interval)
        self.flood_extra = float(flood_extra)
        self.max_flood_wait = float(max_flood_wait)
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
                await interruptible_sleep(delay)
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
        """Run one Telegram RPC with spacing, FloodWait recovery and transient retries.

        * FloodWait / SlowMode: wait the requested time (+margin) and retry, with no
          attempt limit (only waits above `max_flood_wait` are re-raised).
        * Connection/timeout errors: up to `retries` retries with 2s, 8s, 18s... pauses.
        """
        flood_attempts = 0
        transient = 0
        flooded = False
        while True:
            await self.wait(key)
            try:
                result = await fn()
            except FLOOD_ERRORS as exc:
                seconds = max(1, int(getattr(exc, "seconds", 1) or 1))
                if seconds > self.max_flood_wait:
                    raise
                flood_attempts += 1
                await self.penalize(seconds, key)
                flooded = True
                _notify("on_wait", seconds, key)
                if on_flood is not None:
                    try:
                        await on_flood(seconds, flood_attempts)
                    except Exception:
                        pass
                continue  # wait() consumes the cooldown that penalize() reserved
            except TRANSIENT_ERRORS:
                transient += 1
                if transient > int(retries):
                    raise
                await interruptible_sleep(min(30, 2 * transient * transient))
                continue
            if flooded:
                _notify("on_resume")
            return result


# One limiter per process/account. The scanner and private-chat intake therefore
# cannot accidentally send vote RPCs at the same time.
GLOBAL_RATE_LIMITER = RateLimiter(min_interval=1.20, flood_extra=2.0)
# Voting is much more sensitive than ordinary reads. Keep it deliberately slow.
# This is ~20 votes/minute before Telegram has to intervene.
VOTE_RATE_LIMITER = RateLimiter(min_interval=3.0, flood_extra=3.0)
