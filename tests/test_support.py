"""Кэш, ограничитель частоты и JSON-логи."""

from __future__ import annotations

import asyncio
import json
import logging

import pytest
from fastapi import HTTPException

from trip_planner.api.ratelimit import RateLimiter
from trip_planner.cache import AsyncTTLCache
from trip_planner.observability import JsonFormatter, request_id_var


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


async def test_cache_returns_stored_value_until_ttl_expires() -> None:
    clock = Clock()
    cache: AsyncTTLCache[int] = AsyncTTLCache(ttl=10, timer=clock)
    calls = 0

    async def load() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert await cache.get_or_load("k", load) == 1
    clock.now = 9
    assert await cache.get_or_load("k", load) == 1
    clock.now = 11
    assert await cache.get_or_load("k", load) == 2


async def test_cache_does_not_store_errors() -> None:
    cache: AsyncTTLCache[str] = AsyncTTLCache(ttl=10)
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("first call fails")
        return "ok"

    with pytest.raises(RuntimeError):
        await cache.get_or_load("k", flaky)
    assert await cache.get_or_load("k", flaky) == "ok"
    assert len(cache) == 1


async def test_concurrent_requests_for_one_key_load_once() -> None:
    cache: AsyncTTLCache[int] = AsyncTTLCache(ttl=10)
    calls = 0

    async def slow() -> int:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return 42

    results = await asyncio.gather(*(cache.get_or_load("k", slow) for _ in range(5)))

    assert results == [42] * 5
    assert calls == 1


def test_rate_limiter_blocks_and_recovers() -> None:
    clock = Clock()
    limiter = RateLimiter(limit=2, window=60, clock=clock)

    limiter.check("1.1.1.1")
    limiter.check("1.1.1.1")
    with pytest.raises(HTTPException) as blocked:
        limiter.check("1.1.1.1")
    assert blocked.value.status_code == 429

    limiter.check("2.2.2.2")  # другой клиент не затронут
    clock.now = 61
    limiter.check("1.1.1.1")  # окно прошло


def test_json_formatter_includes_request_id() -> None:
    token = request_id_var.set("req-1")
    try:
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "привет %s", ("мир",), None)
        payload = json.loads(JsonFormatter().format(record))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "req-1"
    assert payload["message"] == "привет мир"
    assert payload["level"] == "INFO"
