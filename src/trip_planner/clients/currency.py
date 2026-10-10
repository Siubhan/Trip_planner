"""Frankfurter v2 (курсы ЕЦБ и других провайдеров): курс одной валюты к другой."""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
from pydantic import BaseModel

from trip_planner.clients.base import BaseClient
from trip_planner.errors import CurrencyUnsupported, UpstreamNotFound
from trip_planner.models import CurrencyRate


class _Rate(BaseModel):
    date: date
    base: str
    quote: str
    rate: float


class CurrencyClient(BaseClient):
    name = "frankfurter"

    def __init__(self, http: httpx.AsyncClient, base_url: str, **kwargs: Any) -> None:
        super().__init__(http, **kwargs)
        self._base_url = base_url.rstrip("/")

    async def rate(self, base: str, quote: str) -> CurrencyRate:
        """Сколько единиц `quote` в одной единице `base`."""
        base, quote = base.upper(), quote.upper()
        if base == quote:
            return CurrencyRate(base=base, quote=quote, rate=1.0, date=date.today())
        try:
            data = await self.request_json("GET", f"{self._base_url}/v2/rate/{base}/{quote}")
        except UpstreamNotFound as exc:
            raise CurrencyUnsupported(f"{base}/{quote} is not supported") from exc
        parsed = self.parse(_Rate, data)
        return CurrencyRate(
            base=parsed.base, quote=parsed.quote, rate=parsed.rate, date=parsed.date
        )
