"""Базовый HTTP-клиент: таймаут, ограниченные повторы с растущей паузой, разбор через pydantic."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from trip_planner.errors import (
    UpstreamBadResponse,
    UpstreamNotFound,
    UpstreamTimeout,
    UpstreamUnavailable,
)

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class BaseClient:
    name = "upstream"

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        timeout: float = 5.0,
        retries: int = 2,
        backoff: float = 0.3,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = http
        self._timeout = timeout
        self._retries = retries
        self._backoff = backoff
        self._sleep = sleep

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        timeout_s: float | None = None,
        retries: int | None = None,
        **kwargs: Any,
    ) -> Any:
        """Выполнить запрос и вернуть JSON.

        Повторяем только временные сбои (таймаут, сетевая ошибка, 429/5xx), максимум `retries`
        раз с паузой backoff * 2**n. Остальные 4xx — сразу ошибка без повторов.
        """
        attempts = (self._retries if retries is None else retries) + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            if attempt:
                await self._sleep(self._backoff * 2 ** (attempt - 1))
            try:
                response = await self._http.request(
                    method, url, timeout=timeout_s or self._timeout, **kwargs
                )
            except httpx.TimeoutException:
                last_error = UpstreamTimeout(f"{self.name}: timeout")
                logger.warning("%s: timeout (attempt %d/%d)", self.name, attempt + 1, attempts)
                continue
            except httpx.TransportError as exc:
                last_error = UpstreamUnavailable(f"{self.name}: {type(exc).__name__}")
                logger.warning(
                    "%s: transport error (attempt %d/%d)", self.name, attempt + 1, attempts
                )
                continue

            if response.status_code in RETRY_STATUSES:
                last_error = UpstreamUnavailable(f"{self.name}: HTTP {response.status_code}")
                logger.warning(
                    "%s: HTTP %d (attempt %d/%d)",
                    self.name,
                    response.status_code,
                    attempt + 1,
                    attempts,
                )
                continue
            if response.status_code == 404:
                raise UpstreamNotFound(f"{self.name}: HTTP 404")
            if response.status_code >= 400:
                raise UpstreamBadResponse(f"{self.name}: HTTP {response.status_code}")

            try:
                return response.json()
            except ValueError as exc:
                raise UpstreamBadResponse(f"{self.name}: invalid JSON") from exc

        assert last_error is not None
        raise last_error

    def parse(self, model: type[M], data: Any) -> M:
        """Разобрать ответ источника; неожиданный формат → контролируемая ошибка."""
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            logger.warning("%s: unexpected response shape: %s", self.name, exc.errors()[:3])
            raise UpstreamBadResponse(f"{self.name}: unexpected response format") from exc
