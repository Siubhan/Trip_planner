from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from trip_planner.api.schemas import Block, TripQuery, TripResponse
from trip_planner.config import Settings
from trip_planner.errors import DestinationNotFound, UpstreamUnavailable
from trip_planner.main import create_app
from trip_planner.models import CurrencyRate, Destination, WeatherDay
from trip_planner.services.trip_service import TripService

PARAMS = {
    "destination": "Лиссабон",
    "start": "2026-11-01",
    "end": "2026-11-05",
    "home_currency": "EUR",
}


class FakeService:
    """Подмена сервиса: роуты проверяются отдельно от логики сбора данных."""

    def __init__(self) -> None:
        self.error: Exception | None = None
        self.queries: list[TripQuery] = []

    async def get_trip(self, query: TripQuery) -> TripResponse:
        self.queries.append(query)
        if self.error:
            raise self.error
        return TripResponse(
            destination=Destination(name="Lisboa", lat=38.72, lon=-9.14, country_code="PT"),
            country=Block.failed("upstream_timeout"),
            weather=Block.ok(
                [WeatherDay(date=date(2026, 11, 1), t_min=12.1, t_max=18.4, precip_mm=0.4)]
            ),
            currency=Block.ok(
                CurrencyRate(base="EUR", quote="EUR", rate=1.0, date=date(2026, 10, 8))
            ),
            places=Block.ok([]),
        )


@pytest.fixture
def fake() -> FakeService:
    return FakeService()


@pytest.fixture
def client(settings: Settings, fake: FakeService) -> Iterator[TestClient]:
    app = create_app(settings, service=cast(TripService, fake))
    with TestClient(app) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_trip_returns_partial_result_with_200(client: TestClient) -> None:
    response = client.get("/api/v1/trip", params=PARAMS)

    assert response.status_code == 200
    body = response.json()
    assert body["destination"]["name"] == "Lisboa"
    # сбойный блок содержит только статус и код ошибки, без пустых полей
    assert body["country"] == {"status": "error", "error": "upstream_timeout"}
    assert body["weather"]["status"] == "ok"
    assert body["weather"]["data"][0]["t_max"] == 18.4
    assert body["places"] == {"status": "ok", "data": []}


def test_input_is_normalized(client: TestClient, fake: FakeService) -> None:
    client.get(
        "/api/v1/trip", params={**PARAMS, "destination": "  Лиссабон ", "home_currency": "eur"}
    )
    assert fake.queries[0].destination == "Лиссабон"
    assert fake.queries[0].home_currency == "EUR"


@pytest.mark.parametrize(
    "override",
    [
        {"end": "2026-10-31"},  # конец раньше начала
        {"end": "2026-12-31"},  # слишком длинная поездка
        {"start": "01.11.2026"},  # неверный формат даты
        {"start": "2026-02-30"},  # несуществующая дата
        {"home_currency": "XXX"},  # неизвестный код
        {"home_currency": "euro"},
        {"destination": "a"},  # слишком короткое название
    ],
)
def test_invalid_parameters_give_422(client: TestClient, override: dict[str, str]) -> None:
    response = client.get("/api/v1/trip", params={**PARAMS, **override})
    assert response.status_code == 422


def test_missing_parameter_gives_422(client: TestClient) -> None:
    params = {k: v for k, v in PARAMS.items() if k != "home_currency"}
    assert client.get("/api/v1/trip", params=params).status_code == 422


def test_unknown_destination_gives_404(client: TestClient, fake: FakeService) -> None:
    fake.error = DestinationNotFound("абвгд")
    response = client.get("/api/v1/trip", params=PARAMS)
    assert response.status_code == 404
    assert "абвгд" in response.json()["detail"]


def test_geocoding_outage_gives_502(client: TestClient, fake: FakeService) -> None:
    fake.error = UpstreamUnavailable("nominatim down")
    response = client.get("/api/v1/trip", params=PARAMS)
    assert response.status_code == 502


def test_rate_limit_gives_429(settings: Settings, fake: FakeService) -> None:
    app = create_app(
        settings.model_copy(update={"rate_limit_per_minute": 2}), service=cast(TripService, fake)
    )
    with TestClient(app) as limited:
        assert limited.get("/api/v1/trip", params=PARAMS).status_code == 200
        assert limited.get("/api/v1/trip", params=PARAMS).status_code == 200
        blocked = limited.get("/api/v1/trip", params=PARAMS)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
        # health лимитом не ограничивается
        assert limited.get("/api/v1/health").status_code == 200


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    generated = client.get("/api/v1/health").headers["X-Request-ID"]
    assert len(generated) >= 8
    echoed = client.get("/api/v1/health", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["X-Request-ID"] == "abc-123"


def test_swagger_and_openapi_are_available(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/trip" in paths
    assert "/api/v1/health" in paths


def test_frontend_is_served_when_present(settings: Settings, fake: FakeService) -> None:
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    app = create_app(
        settings.model_copy(update={"frontend_dir": frontend}), service=cast(TripService, fake)
    )
    with TestClient(app) as web:
        page = web.get("/")
        assert page.status_code == 200
        assert "Планировщик поездки" in page.text
        assert 'id="map"' in page.text
        assert web.get("/static/app.js").status_code == 200
        assert web.get("/static/vendor/leaflet/leaflet.js").status_code == 200


def test_api_still_works_without_frontend(client: TestClient) -> None:
    assert client.get("/").status_code == 404
