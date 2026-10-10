from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import date
from typing import Any

import httpx
import pytest
import respx

from tests.conftest import load_fixture
from trip_planner.api.schemas import TripQuery
from trip_planner.config import Settings
from trip_planner.errors import DestinationNotFound, UpstreamError
from trip_planner.main import build_service
from trip_planner.models import Place
from trip_planner.services.trip_service import TripService

NOMINATIM = "https://nominatim.test"
METEO = "https://meteo.test"
FRANKFURTER = "https://rates.test"
COUNTRIES = "https://countries.test"
OVERPASS = "https://overpass.test/api/interpreter"

QUERY = TripQuery(
    destination="Лиссабон", start=date(2026, 11, 1), end=date(2026, 11, 3), home_currency="USD"
)


@pytest.fixture
def test_settings(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "nominatim_url": NOMINATIM,
            "open_meteo_url": METEO,
            "frankfurter_url": FRANKFURTER,
            "restcountries_url": COUNTRIES,
            "overpass_url": OVERPASS,
        }
    )


@pytest.fixture
def make_service(http: httpx.AsyncClient, test_settings: Settings) -> Callable[..., TripService]:
    def factory(today: date = date(2026, 10, 25), settings: Settings | None = None) -> TripService:
        service = build_service(http, settings or test_settings)
        service._today = lambda: today
        return service

    return factory


def mock_all_ok() -> dict[str, respx.Route]:
    return {
        "geo": respx.get(f"{NOMINATIM}/search").respond(json=load_fixture("nominatim_lisbon.json")),
        "weather": respx.get(f"{METEO}/v1/forecast").respond(
            json=load_fixture("open_meteo_lisbon.json")
        ),
        "country": respx.get(f"{COUNTRIES}/countries/v5/codes.alpha_2/PT").respond(
            json=load_fixture("restcountries_pt.json")
        ),
        "rate": respx.get(f"{FRANKFURTER}/v2/rate/USD/EUR").respond(
            json=load_fixture("frankfurter_rate.json")
        ),
        "places": respx.post(OVERPASS).respond(json=load_fixture("overpass_lisbon.json")),
    }


@respx.mock
async def test_all_sources_ok(make_service: Callable[..., TripService]) -> None:
    mock_all_ok()

    result = await make_service().get_trip(QUERY)

    assert result.destination.name == "Lisboa"
    assert result.country.status == "ok"
    assert result.country.data is not None
    assert result.country.data.currency == "EUR"
    assert result.weather.status == "ok"
    assert result.weather.data is not None
    assert len(result.weather.data) == 3
    assert result.weather.warning is None
    assert result.currency.status == "ok"
    assert result.currency.data is not None
    assert result.currency.data.rate == 0.8915
    assert result.places.status == "ok"
    assert result.places.data is not None
    assert len(result.places.data) == 2


@respx.mock
async def test_currency_failure_does_not_break_other_blocks(
    make_service: Callable[..., TripService],
) -> None:
    routes = mock_all_ok()
    routes["rate"].respond(503)

    result = await make_service().get_trip(QUERY)

    assert (result.currency.status, result.currency.error) == ("error", "upstream_unavailable")
    assert result.country.status == "ok"
    assert result.weather.status == "ok"
    assert result.places.status == "ok"


@respx.mock
async def test_country_failure_marks_currency_as_dependent(
    make_service: Callable[..., TripService],
) -> None:
    routes = mock_all_ok()
    routes["country"].respond(500)

    result = await make_service().get_trip(QUERY)

    assert (result.country.status, result.country.error) == ("error", "upstream_unavailable")
    assert (result.currency.status, result.currency.error) == ("error", "dependency_failed")
    assert result.weather.status == "ok"


@respx.mock
async def test_missing_api_key_degrades_gracefully(
    make_service: Callable[..., TripService], test_settings: Settings
) -> None:
    mock_all_ok()
    service = make_service(settings=test_settings.model_copy(update={"restcountries_api_key": ""}))

    result = await service.get_trip(QUERY)

    assert result.country.error == "api_key_missing"
    assert result.currency.error == "dependency_failed"
    assert result.weather.status == "ok"
    assert result.places.status == "ok"


@respx.mock
async def test_weather_and_places_failures_are_isolated(
    make_service: Callable[..., TripService],
) -> None:
    routes = mock_all_ok()
    routes["weather"].mock(side_effect=httpx.ReadTimeout("slow"))
    routes["places"].respond(504)

    result = await make_service().get_trip(QUERY)

    assert result.weather.error == "upstream_timeout"
    assert result.places.error == "upstream_unavailable"
    assert result.country.status == "ok"
    assert result.currency.status == "ok"


@respx.mock
async def test_unknown_destination_raises_not_found(
    make_service: Callable[..., TripService],
) -> None:
    respx.get(f"{NOMINATIM}/search").respond(json=[])
    with pytest.raises(DestinationNotFound):
        await make_service().get_trip(QUERY)


@respx.mock
async def test_geocoding_outage_is_critical(make_service: Callable[..., TripService]) -> None:
    respx.get(f"{NOMINATIM}/search").respond(503)
    with pytest.raises(UpstreamError):
        await make_service().get_trip(QUERY)


@respx.mock
async def test_unexpected_exception_becomes_internal_error(
    make_service: Callable[..., TripService], monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_all_ok()
    service = make_service()

    async def boom(*_: Any, **__: Any) -> list[Place]:
        raise RuntimeError("bug")

    monkeypatch.setattr(service._places, "nearby", boom)

    result = await service.get_trip(QUERY)

    assert result.places.error == "internal_error"
    assert result.country.status == "ok"


@respx.mock
async def test_dates_beyond_forecast_horizon_give_warning_not_error(
    make_service: Callable[..., TripService],
) -> None:
    routes = mock_all_ok()

    # «сегодня» 10 октября: последний день прогноза 24 октября, а поездка в ноябре
    result = await make_service(today=date(2026, 10, 10)).get_trip(QUERY)

    assert result.weather.status == "ok"
    assert result.weather.data == []
    assert result.weather.warning is not None
    assert "2026-10-24" in result.weather.warning
    assert not routes["weather"].called
    assert result.country.status == "ok"


@respx.mock
async def test_partially_covered_trip_is_clipped_with_warning(
    make_service: Callable[..., TripService],
) -> None:
    routes = mock_all_ok()
    query = QUERY.model_copy(update={"start": date(2026, 10, 20), "end": date(2026, 11, 3)})

    result = await make_service(today=date(2026, 10, 10)).get_trip(query)

    params = routes["weather"].calls.last.request.url.params
    assert (params["start_date"], params["end_date"]) == ("2026-10-20", "2026-10-24")
    assert result.weather.warning is not None


@respx.mock
async def test_second_request_is_served_from_cache(
    make_service: Callable[..., TripService],
) -> None:
    routes = mock_all_ok()
    service = make_service()

    await service.get_trip(QUERY)
    await service.get_trip(QUERY.model_copy(update={"destination": " лиссабон "}))

    for name, route in routes.items():
        assert route.call_count == 1, f"{name} вызван повторно"


@respx.mock
async def test_blocks_are_requested_in_parallel(make_service: Callable[..., TripService]) -> None:
    routes = mock_all_ok()
    delay = 0.2

    def slow(fixture: str, *, status: int = 200) -> Callable[[httpx.Request], Any]:
        async def handler(_: httpx.Request) -> httpx.Response:
            await asyncio.sleep(delay)
            return httpx.Response(status, json=load_fixture(fixture))

        return handler

    routes["weather"].mock(side_effect=slow("open_meteo_lisbon.json"))
    routes["country"].mock(side_effect=slow("restcountries_pt.json"))
    routes["places"].mock(side_effect=slow("overpass_lisbon.json"))
    routes["rate"].mock(side_effect=slow("frankfurter_rate.json"))

    started = time.perf_counter()
    result = await make_service().get_trip(QUERY)
    elapsed = time.perf_counter() - started

    assert result.currency.status == "ok"
    # Последовательно вышло бы 4 * delay = 0.8 с; параллельно: страна → курс, т.е. ≈ 2 * delay
    assert elapsed < 3.5 * delay
