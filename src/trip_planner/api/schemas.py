"""Схемы собственного API. Каждый блок — либо данные, либо описание ошибки."""

from __future__ import annotations

from datetime import date
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, Field

from trip_planner.models import (
    CountryData,
    CurrencyRate,
    Destination,
    Place,
    WeatherDay,
)

T = TypeVar("T")


class Block(BaseModel, Generic[T]):  # noqa: UP046 — Generic нужен для FastAPI/pydantic
    status: Literal["ok", "error"]
    data: T | None = None
    error: str | None = None
    warning: str | None = None

    @classmethod
    def ok(cls, data: T, warning: str | None = None) -> Block[T]:
        return cls(status="ok", data=data, warning=warning)

    @classmethod
    def failed(cls, code: str) -> Block[T]:
        return cls(status="error", error=code)


class TripResponse(BaseModel):
    destination: Destination
    country: Block[CountryData]
    weather: Block[list[WeatherDay]]
    currency: Block[CurrencyRate]
    places: Block[list[Place]]


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class TripQuery(BaseModel):
    """Проверенные параметры запроса к /api/v1/trip."""

    destination: str = Field(min_length=2, max_length=100)
    start: date
    end: date
    home_currency: str = Field(pattern=r"^[A-Z]{3}$")
