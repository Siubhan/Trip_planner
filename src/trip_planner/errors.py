"""Контролируемые ошибки: каждая несёт короткий машинный код для блока ответа."""

from __future__ import annotations


class UpstreamError(Exception):
    """Сбой внешнего источника. `code` попадает в поле `error` блока ответа."""

    code = "upstream_error"

    def __init__(self, message: str = "") -> None:
        super().__init__(message or self.code)


class UpstreamTimeout(UpstreamError):
    code = "upstream_timeout"


class UpstreamUnavailable(UpstreamError):
    code = "upstream_unavailable"


class UpstreamBadResponse(UpstreamError):
    """Источник ответил, но формат неожиданный."""

    code = "upstream_bad_response"


class UpstreamNotFound(UpstreamError):
    """Источник ответил 404: ресурса нет (например, неизвестная валюта)."""

    code = "upstream_not_found"


class CurrencyUnsupported(UpstreamError):
    code = "currency_unsupported"


class NotConfigured(UpstreamError):
    """Для источника не задан обязательный параметр (например, API-ключ)."""

    code = "api_key_missing"


class CountryUnknown(UpstreamError):
    """Геокодинг не вернул код страны, справку получить не по чему."""

    code = "country_unknown"


class DependencyFailed(UpstreamError):
    """Блок зависит от другого блока, который не сработал."""

    code = "dependency_failed"


class DestinationNotFound(Exception):
    """Геокодинг отработал, но места с таким названием нет → HTTP 404."""
