"""Overpass API: достопримечательности вокруг точки (малый радиус, короткий таймаут)."""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field

from trip_planner.clients.base import BaseClient
from trip_planner.errors import UpstreamBadResponse
from trip_planner.models import Place

_TOURISM = "attraction|museum|viewpoint|gallery|artwork"
_HISTORIC = "monument|castle|ruins|memorial|archaeological_site|fort"


class _Point(BaseModel):
    lat: float
    lon: float


class _Element(BaseModel):
    lat: float | None = None
    lon: float | None = None
    center: _Point | None = None
    tags: dict[str, str] = Field(default_factory=dict)


class _Overpass(BaseModel):
    elements: list[_Element]


def build_query(lat: float, lon: float, radius_m: int, limit: int) -> str:
    around = f"around:{int(radius_m)},{lat:.5f},{lon:.5f}"
    return (
        "[out:json][timeout:8];("
        f'nwr({around})["tourism"~"^({_TOURISM})$"]["name"];'
        f'nwr({around})["historic"~"^({_HISTORIC})$"]["name"];'
        f");out center {int(limit) * 3};"
    )


class PlacesClient(BaseClient):
    name = "overpass"

    def __init__(
        self,
        http: httpx.AsyncClient,
        url: str,
        *,
        overpass_timeout: float = 10.0,
        overpass_retries: int = 1,
        **kwargs: Any,
    ) -> None:
        super().__init__(http, **kwargs)
        self._url = url
        self._timeout_override = overpass_timeout
        self._retries_override = overpass_retries

    async def nearby(self, lat: float, lon: float, radius_m: int, limit: int) -> list[Place]:
        data = await self.request_json(
            "POST",
            self._url,
            data={"data": build_query(lat, lon, radius_m, limit)},
            timeout_s=self._timeout_override,
            retries=self._retries_override,
        )
        if not isinstance(data, dict):
            raise UpstreamBadResponse("overpass: expected an object")

        places: list[Place] = []
        seen: set[str] = set()
        for element in self.parse(_Overpass, data).elements:
            point = (
                (element.lat, element.lon)
                if element.lat is not None and element.lon is not None
                else (element.center.lat, element.center.lon)
                if element.center
                else None
            )
            name = element.tags.get("name")
            category = element.tags.get("tourism") or element.tags.get("historic")
            if point is None or not name or not category or name in seen:
                continue
            seen.add(name)
            places.append(Place(name=name, lat=point[0], lon=point[1], category=category))
            if len(places) >= limit:
                break
        return places
