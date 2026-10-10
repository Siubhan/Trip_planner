from __future__ import annotations

import httpx
import pytest
import respx
from pydantic import BaseModel

from tests.conftest import no_sleep
from trip_planner.clients.base import BaseClient
from trip_planner.errors import (
    UpstreamBadResponse,
    UpstreamNotFound,
    UpstreamTimeout,
    UpstreamUnavailable,
)

URL = "https://api.example.test/data"


def make_client(http: httpx.AsyncClient, sleeps: list[float] | None = None) -> BaseClient:
    async def record(seconds: float) -> None:
        if sleeps is not None:
            sleeps.append(seconds)

    return BaseClient(http, retries=2, backoff=0.5, sleep=record)


@respx.mock
async def test_returns_json(http: httpx.AsyncClient) -> None:
    respx.get(URL).respond(json={"ok": True})
    assert await make_client(http).request_json("GET", URL) == {"ok": True}


@respx.mock
async def test_retries_server_errors_with_growing_pause(http: httpx.AsyncClient) -> None:
    route = respx.get(URL).mock(
        side_effect=[httpx.Response(503), httpx.Response(502), httpx.Response(200, json={"n": 3})]
    )
    sleeps: list[float] = []
    assert await make_client(http, sleeps).request_json("GET", URL) == {"n": 3}
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]


@respx.mock
async def test_gives_up_after_two_retries(http: httpx.AsyncClient) -> None:
    route = respx.get(URL).respond(500)
    with pytest.raises(UpstreamUnavailable):
        await make_client(http).request_json("GET", URL)
    assert route.call_count == 3  # первый вызов + 2 повтора


@respx.mock
async def test_timeout_maps_to_upstream_timeout(http: httpx.AsyncClient) -> None:
    respx.get(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(UpstreamTimeout):
        await make_client(http).request_json("GET", URL)


@respx.mock
async def test_network_error_maps_to_unavailable(http: httpx.AsyncClient) -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(UpstreamUnavailable):
        await make_client(http).request_json("GET", URL)


@respx.mock
async def test_client_errors_are_not_retried(http: httpx.AsyncClient) -> None:
    route = respx.get(URL).respond(400)
    with pytest.raises(UpstreamBadResponse):
        await make_client(http).request_json("GET", URL)
    assert route.call_count == 1


@respx.mock
async def test_404_maps_to_not_found(http: httpx.AsyncClient) -> None:
    respx.get(URL).respond(404)
    with pytest.raises(UpstreamNotFound):
        await make_client(http).request_json("GET", URL)


@respx.mock
async def test_invalid_json_is_bad_response(http: httpx.AsyncClient) -> None:
    respx.get(URL).respond(200, text="<html>oops</html>")
    with pytest.raises(UpstreamBadResponse):
        await make_client(http).request_json("GET", URL)


class _Model(BaseModel):
    value: int


def test_parse_wraps_validation_errors(http: httpx.AsyncClient) -> None:
    client = BaseClient(http, sleep=no_sleep)
    assert client.parse(_Model, {"value": 1}).value == 1
    with pytest.raises(UpstreamBadResponse):
        client.parse(_Model, {"value": "not a number"})
