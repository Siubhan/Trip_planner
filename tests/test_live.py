"""Необязательная проверка на реальных API. Запуск вручную: `pytest -m live`.

Нужна сеть и (для блока страны) переменная TRIP_RESTCOUNTRIES_API_KEY. Тест не входит в CI:
он проверяет, что внешние сервисы по-прежнему отвечают в ожидаемом формате.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from trip_planner.api.schemas import TripQuery
from trip_planner.config import Settings
from trip_planner.main import build_service

pytestmark = pytest.mark.live


async def test_real_apis_return_expected_shapes() -> None:
    settings = Settings()
    start = datetime.now(UTC).date() + timedelta(days=2)
    query = TripQuery(
        destination="Lisbon",
        start=start,
        end=start + timedelta(days=2),
        home_currency="USD",
    )
    async with httpx.AsyncClient(headers={"User-Agent": settings.user_agent}) as http:
        result = await build_service(http, settings).get_trip(query)

    assert result.destination.country_code == "PT"
    assert result.weather.status == "ok", result.weather.error
    assert result.places.status == "ok", result.places.error
    if settings.restcountries_api_key:
        assert result.country.status == "ok", result.country.error
        assert result.currency.status == "ok", result.currency.error
