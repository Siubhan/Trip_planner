from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from trip_planner import __version__
from trip_planner.api.ratelimit import rate_limit
from trip_planner.api.schemas import ErrorResponse, HealthResponse, TripQuery, TripResponse
from trip_planner.currencies import KNOWN_CURRENCIES
from trip_planner.services.trip_service import TripService

router = APIRouter(prefix="/api/v1")


def get_service(request: Request) -> TripService:
    service: TripService = request.app.state.service
    return service


def validate_query(
    request: Request,
    destination: Annotated[str, Query(min_length=2, max_length=100, examples=["Лиссабон"])],
    start: Annotated[date, Query(description="Начало поездки, ISO 8601", examples=["2026-11-01"])],
    end: Annotated[date, Query(description="Конец поездки, ISO 8601", examples=["2026-11-05"])],
    home_currency: Annotated[
        str, Query(description="Код домашней валюты, ISO 4217", examples=["EUR"])
    ],
) -> TripQuery:
    """Проверки FR-9, которые нельзя выразить типами: порядок дат, длина, известный код валюты."""
    if end < start:
        raise HTTPException(422, "Дата окончания не может быть раньше даты начала.")
    max_days = request.app.state.settings.max_trip_days
    if (end - start).days + 1 > max_days:
        raise HTTPException(422, f"Поездка не может быть длиннее {max_days} дней.")
    code = home_currency.strip().upper()
    if code not in KNOWN_CURRENCIES:
        raise HTTPException(422, f"Неизвестный код валюты: {home_currency!r}.")
    return TripQuery(destination=destination.strip(), start=start, end=end, home_currency=code)


@router.get(
    "/trip",
    response_model=TripResponse,
    response_model_exclude_none=True,
    summary="Сводка по поездке",
    responses={
        404: {"model": ErrorResponse, "description": "Назначение не найдено"},
        422: {"model": ErrorResponse, "description": "Неверные параметры"},
        429: {"model": ErrorResponse, "description": "Превышен лимит запросов"},
        502: {"model": ErrorResponse, "description": "Геокодинг недоступен"},
    },
    dependencies=[Depends(rate_limit)],
)
async def trip(
    query: Annotated[TripQuery, Depends(validate_query)],
    service: Annotated[TripService, Depends(get_service)],
) -> TripResponse:
    return await service.get_trip(query)


@router.get("/health", response_model=HealthResponse, summary="Проверка живости")
async def health() -> HealthResponse:
    return HealthResponse(version=__version__)
