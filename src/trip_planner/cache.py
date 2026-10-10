"""Асинхронный TTL-кэш с защитой от «толпы»: параллельные запросы одного ключа ждут один вызов."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Hashable

from cachetools import TTLCache


class AsyncTTLCache[T]:
    def __init__(
        self,
        ttl: float,
        maxsize: int = 1024,
        timer: Callable[[], float] = time.monotonic,
    ) -> None:
        self._store: TTLCache[Hashable, T] = TTLCache(maxsize=maxsize, ttl=ttl, timer=timer)
        self._locks: dict[Hashable, asyncio.Lock] = {}

    async def get_or_load(self, key: Hashable, loader: Callable[[], Awaitable[T]]) -> T:
        """Вернуть значение из кэша или вызвать `loader`. Ошибки не кэшируются."""
        try:
            return self._store[key]
        except KeyError:
            pass

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                return self._store[key]
            except KeyError:
                pass
            try:
                value = await loader()
                self._store[key] = value
                return value
            finally:
                self._locks.pop(key, None)

    def __len__(self) -> int:
        return len(self._store)
