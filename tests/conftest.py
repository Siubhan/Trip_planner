from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from trip_planner.config import Settings

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def settings() -> Settings:
    # _env_file=None: тесты не должны зависеть от локального .env
    return Settings(
        _env_file=None,
        restcountries_api_key="test-key",
        nominatim_min_interval=0,
        retry_backoff=0,
        rate_limit_per_minute=1000,
        frontend_dir=Path("does-not-exist"),
    )


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


async def no_sleep(_: float) -> None:
    return None
