"""Nominatim (OpenStreetMap): координаты и страна по названию.

Правила политики использования: свой User-Agent, не чаще 1 запроса в секунду, кэшировать
результаты (кэш живёт в сервисе), не использовать для автодополнения.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import BaseModel

from trip_planner.clients.base import BaseClient
from trip_planner.errors import DestinationNotFound, UpstreamBadResponse
from trip_planner.models import Destination


class _Address(BaseModel):
    country_code: str | None = None


class _NominatimItem(BaseModel):
    lat: float
    lon: float
    name: str | None = None
    display_name: str
    address: _Address | None = None


class GeocodingClient(BaseClient):
    name = "nominatim"

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        *,
        min_interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        **kwargs: Any,
    ) -> None:
        super().__init__(http, **kwargs)
        self._base_url = base_url.rstrip("/")
        self._min_interval = min_interval
        self._clock = clock
        self._gate = asyncio.Lock()
        self._last_call: float | None = None

    async def _throttle(self) -> None:
        """Выдерживаем паузу между запросами: параллельные вызовы встают в очередь."""
        async with self._gate:
            if self._last_call is not None:
                wait = self._min_interval - (self._clock() - self._last_call)
                if wait > 0:
                    await self._sleep(wait)
            self._last_call = self._clock()

    async def geocode(self, query: str) -> Destination:
        await self._throttle()
        data = await self.request_json(
            "GET",
            f"{self._base_url}/search",
            params={
                "q": query,
                "format": "jsonv2",
                "addressdetails": 1,
                "limit": 1,
                "accept-language": "ru",
            },
        )
        if not isinstance(data, list):
            raise UpstreamBadResponse("nominatim: expected a list")
        if not data:
            raise DestinationNotFound(query)

        item = self.parse(_NominatimItem, data[0])
        name = item.name or item.display_name.split(",")[0].strip()
        raw_code = item.address.country_code if item.address else None
        code = raw_code.upper() if raw_code else None
        return Destination(name=name, lat=item.lat, lon=item.lon, country_code=code)
