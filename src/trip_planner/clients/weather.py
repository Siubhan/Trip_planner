"""Open-Meteo: дневной прогноз (мин./макс. температура, сумма осадков)."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel

from trip_planner.clients.base import BaseClient
from trip_planner.models import WeatherDay


class _Daily(BaseModel):
    time: list[date]
    temperature_2m_min: list[float | None]
    temperature_2m_max: list[float | None]
    precipitation_sum: list[float | None]


class _Forecast(BaseModel):
    daily: _Daily


class WeatherClient(BaseClient):
    name = "open-meteo"

    def __init__(self, http: httpx.AsyncClient, base_url: str, **kwargs: Any) -> None:
        super().__init__(http, **kwargs)
        self._base_url = base_url.rstrip("/")

    async def daily_forecast(
        self, lat: float, lon: float, start: date, end: date
    ) -> list[WeatherDay]:
        data = await self.request_json(
            "GET",
            f"{self._base_url}/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum",
                "timezone": "auto",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
            },
        )
        daily = self.parse(_Forecast, data).daily
        return [
            WeatherDay(date=d, t_min=lo, t_max=hi, precip_mm=p)
            for d, lo, hi, p in zip(
                daily.time,
                daily.temperature_2m_min,
                daily.temperature_2m_max,
                daily.precipitation_sum,
                strict=True,
            )
        ]
