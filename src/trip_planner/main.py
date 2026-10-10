from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from trip_planner import __version__
from trip_planner.api.ratelimit import RateLimiter
from trip_planner.api.routes import router
from trip_planner.clients.country import CountryClient
from trip_planner.clients.currency import CurrencyClient
from trip_planner.clients.geocoding import GeocodingClient
from trip_planner.clients.places import PlacesClient
from trip_planner.clients.weather import WeatherClient
from trip_planner.config import Settings, get_settings
from trip_planner.errors import DestinationNotFound, UpstreamError
from trip_planner.observability import RequestIdMiddleware, setup_logging
from trip_planner.services.trip_service import TripService

logger = logging.getLogger(__name__)


def build_service(http: httpx.AsyncClient, settings: Settings) -> TripService:
    common: dict[str, Any] = {
        "timeout": settings.http_timeout,
        "retries": settings.http_retries,
        "backoff": settings.retry_backoff,
    }
    return TripService(
        geocoder=GeocodingClient(
            http, settings.nominatim_url, min_interval=settings.nominatim_min_interval, **common
        ),
        weather=WeatherClient(http, settings.open_meteo_url, **common),
        currency=CurrencyClient(http, settings.frankfurter_url, **common),
        country=CountryClient(
            http, settings.restcountries_url, settings.restcountries_api_key, **common
        ),
        places=PlacesClient(
            http,
            settings.overpass_url,
            overpass_timeout=settings.overpass_timeout,
            overpass_retries=settings.overpass_retries,
            **common,
        ),
        settings=settings,
    )


def create_app(settings: Settings | None = None, service: TripService | None = None) -> FastAPI:
    settings = settings or get_settings()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if service is not None:
            app.state.service = service
            yield
            return
        async with httpx.AsyncClient(
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
            follow_redirects=True,
        ) as http:
            app.state.service = build_service(http, settings)
            yield

    app = FastAPI(
        title="Trip Planner",
        version=__version__,
        description="Погода, курс валюты, справка о стране и места на карте в одном ответе.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.rate_limiter = RateLimiter(settings.rate_limit_per_minute)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(router)

    @app.exception_handler(DestinationNotFound)
    async def _not_found(_: Request, exc: DestinationNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"Место не найдено: {exc}"})

    @app.exception_handler(UpstreamError)
    async def _upstream(_: Request, exc: UpstreamError) -> JSONResponse:
        # Сюда доходит только сбой критичного источника (геокодинг).
        logger.error("geocoding failed: %s", exc.code)
        return JSONResponse(
            status_code=502,
            content={"detail": f"Сервис геокодинга недоступен ({exc.code})."},
        )

    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    frontend = settings.frontend_dir
    templates_dir, static_dir = frontend / "templates", frontend / "static"
    if not (templates_dir / "index.html").is_file():
        logger.warning("frontend not found at %s, serving API only", frontend.resolve())
        return

    templates = Jinja2Templates(directory=str(templates_dir))
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "index.html", {"version": __version__})


app = create_app()
