"""Доменные модели: то, что клиенты возвращают сервису (не сырые ответы внешних API)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class Destination(BaseModel):
    name: str
    lat: float
    lon: float
    country_code: str | None = None


class WeatherDay(BaseModel):
    date: date
    t_min: float | None
    t_max: float | None
    precip_mm: float | None


class CurrencyInfo(BaseModel):
    code: str
    name: str | None = None
    symbol: str | None = None


class CountryData(BaseModel):
    name: str
    capital: str | None = None
    languages: list[str]
    currency: str | None = None
    currencies: list[CurrencyInfo]
    timezones: list[str]
    flag_emoji: str | None = None
    flag_url: str | None = None


class CurrencyRate(BaseModel):
    base: str
    quote: str
    rate: float
    date: date


class Place(BaseModel):
    name: str
    lat: float
    lon: float
    category: str
