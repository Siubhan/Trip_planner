"""Простое ограничение частоты: скользящее окно в памяти, по IP клиента.

Для одного процесса этого достаточно; при нескольких воркерах лимит нужно выносить в Redis.
За обратным прокси (Render, Fly.io) запустите uvicorn с `--proxy-headers`, тогда
`request.client.host` будет реальным адресом клиента.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(
        self,
        limit: int,
        window: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def check(self, key: str) -> None:
        now = self._clock()
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            retry_after = max(1, int(self._window - (now - hits[0])) + 1)
            raise HTTPException(
                status_code=429,
                detail="Слишком много запросов, попробуйте позже.",
                headers={"Retry-After": str(retry_after)},
            )
        hits.append(now)
        if len(self._hits) > 10_000:  # защита памяти от переполнения чужими ключами
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self._window}


def rate_limit(request: Request) -> None:
    limiter: RateLimiter = request.app.state.rate_limiter
    limiter.check(request.client.host if request.client else "unknown")
