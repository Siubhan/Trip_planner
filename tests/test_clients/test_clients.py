from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from tests.conftest import load_fixture, no_sleep
from trip_planner.clients.country import CountryClient
from trip_planner.clients.currency import CurrencyClient
from trip_planner.clients.geocoding import GeocodingClient
from trip_planner.clients.places import PlacesClient, build_query
from trip_planner.clients.weather import WeatherClient
from trip_planner.errors import (
    CurrencyUnsupported,
    DestinationNotFound,
    NotConfigured,
    UpstreamBadResponse,
)

NOMINATIM = "https://nominatim.test"
METEO = "https://meteo.test"
FRANKFURTER = "https://rates.test"
COUNTRIES = "https://countries.test"
OVERPASS = "https://overpass.test/api/interpreter"


# --- геокодинг ---------------------------------------------------------------------------


@respx.mock
async def test_geocoding_parses_coordinates_and_country(http: httpx.AsyncClient) -> None:
    route = respx.get(f"{NOMINATIM}/search").respond(json=load_fixture("nominatim_lisbon.json"))
    client = GeocodingClient(http, NOMINATIM, min_interval=0, sleep=no_sleep)

    result = await client.geocode("Лиссабон")

    assert (result.name, result.country_code) == ("Lisboa", "PT")
    assert result.lat == pytest.approx(38.7077507)
    assert result.lon == pytest.approx(-9.1365919)
    assert route.calls.last.request.url.params["q"] == "Лиссабон"


@respx.mock
async def test_geocoding_empty_result_is_not_found(http: httpx.AsyncClient) -> None:
    respx.get(f"{NOMINATIM}/search").respond(json=[])
    client = GeocodingClient(http, NOMINATIM, min_interval=0, sleep=no_sleep)
    with pytest.raises(DestinationNotFound):
        await client.geocode("asdkjhqwe")


@respx.mock
async def test_geocoding_unexpected_shape(http: httpx.AsyncClient) -> None:
    respx.get(f"{NOMINATIM}/search").respond(json={"error": "boom"})
    client = GeocodingClient(http, NOMINATIM, min_interval=0, sleep=no_sleep)
    with pytest.raises(UpstreamBadResponse):
        await client.geocode("Lisbon")


@respx.mock
async def test_geocoding_throttles_consecutive_requests(http: httpx.AsyncClient) -> None:
    respx.get(f"{NOMINATIM}/search").respond(json=load_fixture("nominatim_lisbon.json"))
    now = [100.0]
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = GeocodingClient(
        http, NOMINATIM, min_interval=1.0, clock=lambda: now[0], sleep=fake_sleep
    )
    await client.geocode("a1")
    now[0] += 0.25  # второй запрос пришёл через 0.25 с
    await client.geocode("a2")

    assert sleeps == [pytest.approx(0.75)]


# --- погода ------------------------------------------------------------------------------


@respx.mock
async def test_weather_parses_daily_forecast(http: httpx.AsyncClient) -> None:
    route = respx.get(f"{METEO}/v1/forecast").respond(json=load_fixture("open_meteo_lisbon.json"))
    client = WeatherClient(http, METEO, sleep=no_sleep)

    days = await client.daily_forecast(38.72, -9.14, date(2026, 11, 1), date(2026, 11, 3))

    assert [d.date for d in days] == [date(2026, 11, 1), date(2026, 11, 2), date(2026, 11, 3)]
    assert (days[0].t_min, days[0].t_max, days[0].precip_mm) == (12.1, 18.4, 0.4)
    assert days[2].t_min is None  # пропуски в данных не ломают разбор
    params = route.calls.last.request.url.params
    assert params["start_date"] == "2026-11-01"
    assert params["timezone"] == "auto"


@respx.mock
async def test_weather_rejects_unexpected_shape(http: httpx.AsyncClient) -> None:
    respx.get(f"{METEO}/v1/forecast").respond(json={"daily": {"time": ["2026-11-01"]}})
    client = WeatherClient(http, METEO, sleep=no_sleep)
    with pytest.raises(UpstreamBadResponse):
        await client.daily_forecast(1, 1, date(2026, 11, 1), date(2026, 11, 1))


# --- курс валюты -------------------------------------------------------------------------


@respx.mock
async def test_currency_rate(http: httpx.AsyncClient) -> None:
    respx.get(f"{FRANKFURTER}/v2/rate/USD/EUR").respond(json=load_fixture("frankfurter_rate.json"))
    client = CurrencyClient(http, FRANKFURTER, sleep=no_sleep)

    rate = await client.rate("usd", "eur")

    assert (rate.base, rate.quote, rate.rate) == ("USD", "EUR", 0.8915)
    assert rate.date == date(2026, 10, 8)


async def test_currency_same_currency_needs_no_request(http: httpx.AsyncClient) -> None:
    client = CurrencyClient(http, FRANKFURTER, sleep=no_sleep)
    assert (await client.rate("EUR", "EUR")).rate == 1.0


@respx.mock
async def test_currency_unknown_pair_is_unsupported(http: httpx.AsyncClient) -> None:
    respx.get(f"{FRANKFURTER}/v2/rate/USD/XXX").respond(404, json={"message": "not found"})
    client = CurrencyClient(http, FRANKFURTER, sleep=no_sleep)
    with pytest.raises(CurrencyUnsupported):
        await client.rate("USD", "XXX")


# --- справка о стране --------------------------------------------------------------------


@respx.mock
async def test_country_parses_nested_response(http: httpx.AsyncClient) -> None:
    route = respx.get(f"{COUNTRIES}/countries/v5/codes.alpha_2/PT").respond(
        json=load_fixture("restcountries_pt.json")
    )
    client = CountryClient(http, COUNTRIES, "secret", sleep=no_sleep)

    country = await client.by_code("pt")

    assert country.name == "Portugal"
    assert country.capital == "Lisbon"
    assert country.languages == ["Portuguese"]
    assert country.currency == "EUR"
    assert country.currencies[0].symbol == "€"
    assert country.timezones == ["UTC-01:00", "UTC+00:00"]
    assert country.flag_emoji == "🇵🇹"
    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"


@respx.mock
async def test_country_tolerates_list_style_currencies(http: httpx.AsyncClient) -> None:
    respx.get(f"{COUNTRIES}/countries/v5/codes.alpha_2/PT").respond(
        json=load_fixture("restcountries_pt_list_format.json")
    )
    client = CountryClient(http, COUNTRIES, "secret", sleep=no_sleep)

    country = await client.by_code("PT")

    assert country.currency == "EUR"
    assert country.languages == ["Portuguese"]


async def test_country_requires_api_key(http: httpx.AsyncClient) -> None:
    client = CountryClient(http, COUNTRIES, "", sleep=no_sleep)
    with pytest.raises(NotConfigured):
        await client.by_code("PT")


@respx.mock
async def test_country_empty_result(http: httpx.AsyncClient) -> None:
    respx.get(f"{COUNTRIES}/countries/v5/codes.alpha_2/ZZ").respond(json={"data": {"objects": []}})
    client = CountryClient(http, COUNTRIES, "secret", sleep=no_sleep)
    with pytest.raises(UpstreamBadResponse):
        await client.by_code("ZZ")


# --- места -------------------------------------------------------------------------------


@respx.mock
async def test_places_parse_dedupe_and_center(http: httpx.AsyncClient) -> None:
    route = respx.post(OVERPASS).respond(json=load_fixture("overpass_lisbon.json"))
    client = PlacesClient(http, OVERPASS, sleep=no_sleep)

    places = await client.nearby(38.71, -9.13, 3000, 20)

    # дубль «Rossio» и объект без имени отброшены, у way координаты берутся из center
    assert [(p.name, p.category) for p in places] == [
        ("Rossio", "attraction"),
        ("Castelo de São Jorge", "castle"),
    ]
    assert places[1].lat == pytest.approx(38.7110)
    assert b"around%3A3000" in route.calls.last.request.content


@respx.mock
async def test_places_respects_limit(http: httpx.AsyncClient) -> None:
    respx.post(OVERPASS).respond(json=load_fixture("overpass_lisbon.json"))
    client = PlacesClient(http, OVERPASS, sleep=no_sleep)
    assert len(await client.nearby(38.71, -9.13, 3000, 1)) == 1


def test_overpass_query_contains_radius_and_center() -> None:
    query = build_query(38.7, -9.1, 2500, 10)
    assert "around:2500,38.70000,-9.10000" in query
    assert "out center" in query
