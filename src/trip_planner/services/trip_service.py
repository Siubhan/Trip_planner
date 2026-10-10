"""Сборка ответа: геокодинг, затем параллельно страна, погода, места и курс.

Геокодинг критичен: без координат ответ невозможен, поэтому его ошибки пробрасываются наверх.
Остальные блоки изолированы: сбой одного превращается в `status: error` внутри блока.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import TypeVar

from trip_planner.api.schemas import Block, TripQuery, TripResponse
from trip_planner.cache import AsyncTTLCache
from trip_planner.clients.country import CountryClient
from trip_planner.clients.currency import CurrencyClient
from trip_planner.clients.geocoding import GeocodingClient
from trip_planner.clients.places import PlacesClient
from trip_planner.clients.weather import WeatherClient
from trip_planner.config import Settings
from trip_planner.errors import CountryUnknown, DependencyFailed, UpstreamError
from trip_planner.models import (
    CountryData,
    CurrencyRate,
    Destination,
    Place,
    WeatherDay,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _utc_today() -> date:
    return datetime.now(UTC).date()


class TripService:
    def __init__(
        self,
        *,
        geocoder: GeocodingClient,
        weather: WeatherClient,
        currency: CurrencyClient,
        country: CountryClient,
        places: PlacesClient,
        settings: Settings,
        today: Callable[[], date] = _utc_today,
    ) -> None:
        self._geocoder = geocoder
        self._weather = weather
        self._currency = currency
        self._country = country
        self._places = places
        self._settings = settings
        self._today = today

        self._geo_cache: AsyncTTLCache[Destination] = AsyncTTLCache(settings.cache_ttl_geocoding)
        self._country_cache: AsyncTTLCache[CountryData] = AsyncTTLCache(settings.cache_ttl_country)
        self._currency_cache: AsyncTTLCache[CurrencyRate] = AsyncTTLCache(
            settings.cache_ttl_currency
        )
        self._weather_cache: AsyncTTLCache[list[WeatherDay]] = AsyncTTLCache(
            settings.cache_ttl_weather
        )
        self._places_cache: AsyncTTLCache[list[Place]] = AsyncTTLCache(settings.cache_ttl_places)

    async def get_trip(self, query: TripQuery) -> TripResponse:
        # Критичный источник: DestinationNotFound и UpstreamError уходят в API-слой (404 / 502).
        destination = await self._geo_cache.get_or_load(
            query.destination.strip().casefold(),
            lambda: self._geocoder.geocode(query.destination.strip()),
        )

        country_task = asyncio.create_task(self._guard(self._load_country(destination)))
        country, weather, places, currency = await asyncio.gather(
            country_task,
            self._guard_weather(destination, query),
            self._guard(self._load_places(destination)),
            self._guard(self._load_currency(query.home_currency, country_task)),
        )
        return TripResponse(
            destination=destination,
            country=country,
            weather=weather,
            currency=currency,
            places=places,
        )

    # --- блоки -----------------------------------------------------------------------------

    async def _guard(self, work: Awaitable[T]) -> Block[T]:
        try:
            return Block.ok(await work)
        except UpstreamError as exc:
            logger.warning("block failed: %s (%s)", exc.code, exc)
            return Block.failed(exc.code)
        except Exception:
            logger.exception("block crashed unexpectedly")
            return Block.failed("internal_error")

    async def _load_country(self, destination: Destination) -> CountryData:
        code = destination.country_code
        if not code:
            raise CountryUnknown("geocoder returned no country code")
        return await self._country_cache.get_or_load(code, lambda: self._country.by_code(code))

    async def _load_currency(
        self, home: str, country_task: asyncio.Task[Block[CountryData]]
    ) -> CurrencyRate:
        country = await country_task
        if country.status != "ok" or country.data is None or not country.data.currency:
            raise DependencyFailed("destination currency is unknown")
        quote = country.data.currency
        return await self._currency_cache.get_or_load(
            (home, quote), lambda: self._currency.rate(home, quote)
        )

    async def _load_places(self, destination: Destination) -> list[Place]:
        s = self._settings
        key = (round(destination.lat, 3), round(destination.lon, 3), s.places_radius_m)
        return await self._places_cache.get_or_load(
            key,
            lambda: self._places.nearby(
                destination.lat, destination.lon, s.places_radius_m, s.places_limit
            ),
        )

    async def _guard_weather(
        self, destination: Destination, query: TripQuery
    ) -> Block[list[WeatherDay]]:
        # Open-Meteo даёт прогноз примерно на 16 дней вперёд. Дату «сегодня» в точке назначения
        # мы не знаем, поэтому берём запас в день: окно [вчера, сегодня + горизонт - 2] по UTC
        # безопасно для любого часового пояса.
        today = self._today()
        earliest = today - timedelta(days=1)
        latest = today + timedelta(days=self._settings.forecast_horizon_days - 2)
        start, end = max(query.start, earliest), min(query.end, latest)

        warning: str | None = None
        if (start, end) != (query.start, query.end):
            warning = (
                f"Прогноз доступен только с {earliest.isoformat()} по {latest.isoformat()}; "
                "для остальных дат поездки данных нет."
            )
        if start > end:
            return Block.ok([], warning=warning)

        key = (round(destination.lat, 2), round(destination.lon, 2), start, end)
        block = await self._guard(
            self._weather_cache.get_or_load(
                key,
                lambda: self._weather.daily_forecast(destination.lat, destination.lon, start, end),
            )
        )
        block.warning = warning
        return block
