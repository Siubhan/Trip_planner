from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки сервиса. Все значения переопределяются переменными `TRIP_*`."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRIP_", extra="ignore")

    # Идентификация перед Nominatim/Overpass обязательна: укажите свой контакт.
    user_agent: str = (
        "trip-planner/0.1 (learning project; https://github.com/your-name/trip-planner)"
    )

    # HTTP-клиент
    http_timeout: float = 5.0
    http_retries: int = 2
    retry_backoff: float = 0.3

    # Внешние API (URL вынесены в настройки, ключи — только из окружения)
    nominatim_url: str = "https://nominatim.openstreetmap.org"
    nominatim_min_interval: float = 1.0
    open_meteo_url: str = "https://api.open-meteo.com"
    frankfurter_url: str = "https://api.frankfurter.dev"
    restcountries_url: str = "https://api.restcountries.com"
    restcountries_api_key: str = ""
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout: float = 10.0
    overpass_retries: int = 1

    # Прогноз и точки интереса
    forecast_horizon_days: int = 16
    max_trip_days: int = 31
    places_radius_m: int = 3000
    places_limit: int = 20

    # TTL кэша, секунды
    cache_ttl_geocoding: int = 86_400
    cache_ttl_country: int = 86_400
    cache_ttl_currency: int = 3_600
    cache_ttl_weather: int = 1_800
    cache_ttl_places: int = 21_600

    # Ограничение частоты запросов к собственному API
    rate_limit_per_minute: int = 30

    # Фронтенд
    frontend_dir: Path = Path("frontend")
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
