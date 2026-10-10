"""REST Countries v5: справка о стране по коду ISO alpha-2.

Старая v3.1 закрыта, v5 требует API-ключ (бесплатный план: 1000 запросов в месяц, поэтому
справка кэшируется на сутки). Структура ответа вложенная, а формат `currencies` и `languages`
в разных версиях отличается (словарь или список), поэтому разбор терпим к обоим вариантам.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, Field, field_validator

from trip_planner.clients.base import BaseClient
from trip_planner.errors import NotConfigured, UpstreamBadResponse
from trip_planner.models import CountryData, CurrencyInfo

_FIELDS = ",".join(
    [
        "names.common",
        "capitals",
        "languages",
        "currencies",
        "timezones",
        "flag.emoji",
        "flag.url_svg",
        "codes.alpha_2",
    ]
)


class _Names(BaseModel):
    common: str


class _Capital(BaseModel):
    name: str


class _Language(BaseModel):
    name: str


class _Flag(BaseModel):
    emoji: str | None = None
    url_svg: str | None = None


class _Country(BaseModel):
    names: _Names
    capitals: list[_Capital] = Field(default_factory=list)
    languages: list[_Language] = Field(default_factory=list)
    currencies: list[CurrencyInfo] = Field(default_factory=list)
    timezones: list[str] = Field(default_factory=list)
    flag: _Flag | None = None

    @field_validator("currencies", mode="before")
    @classmethod
    def _currencies(cls, value: Any) -> Any:
        # {"EUR": {"name": "Euro", "symbol": "€"}} -> [{"code": "EUR", ...}]
        if isinstance(value, dict):
            return [{"code": code, **(info or {})} for code, info in value.items()]
        return value

    @field_validator("languages", mode="before")
    @classmethod
    def _languages(cls, value: Any) -> Any:
        # {"por": "Portuguese"} -> [{"name": "Portuguese"}]
        if isinstance(value, dict):
            return [{"name": name} for name in value.values()]
        return value


class _Envelope(BaseModel):
    class _Data(BaseModel):
        objects: list[_Country]

    data: _Data


class CountryClient(BaseClient):
    name = "restcountries"

    def __init__(self, http: httpx.AsyncClient, base_url: str, api_key: str, **kwargs: Any) -> None:
        super().__init__(http, **kwargs)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    async def by_code(self, alpha2: str) -> CountryData:
        if not self._api_key:
            raise NotConfigured("TRIP_RESTCOUNTRIES_API_KEY is not set")

        payload = await self.request_json(
            "GET",
            f"{self._base_url}/countries/v5/codes.alpha_2/{alpha2.upper()}",
            params={"response_fields": _FIELDS},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        objects = self.parse(_Envelope, payload).data.objects
        if not objects:
            raise UpstreamBadResponse("restcountries: empty result")

        country = objects[0]
        return CountryData(
            name=country.names.common,
            capital=country.capitals[0].name if country.capitals else None,
            languages=[lang.name for lang in country.languages],
            currency=country.currencies[0].code if country.currencies else None,
            currencies=country.currencies,
            timezones=country.timezones,
            flag_emoji=country.flag.emoji if country.flag else None,
            flag_url=country.flag.url_svg if country.flag else None,
        )
