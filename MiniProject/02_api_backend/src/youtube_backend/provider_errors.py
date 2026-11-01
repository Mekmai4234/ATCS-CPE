"""Sanitized shared error taxonomy; never persist provider bodies/headers/prompts."""

import math
import time
from datetime import UTC
from email.utils import parsedate_to_datetime

from .errors import AppError


def retry_seconds(value):
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            seconds = date.timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            return None
    return seconds if math.isfinite(seconds) and 0 < seconds <= 86400 else None


def provider_error(status, *, retry_after=None, retry_delay_seconds=None, origin="http"):
    code, message, retryable = {
        429: ("provider_rate_limited", "Provider usage is limited", True),
        503: ("provider_unavailable", "Provider is temporarily unavailable", True),
        401: ("provider_configuration", "Provider authentication/configuration rejected", False),
        403: ("provider_configuration", "Provider authentication/configuration rejected", False),
        408: ("provider_timeout", "Provider request timed out", True),
        504: ("provider_timeout", "Provider request timed out", True),
    }.get(status, ("provider_invalid_response", "Provider response is invalid", False))
    if type(status) is int and 500 <= status <= 599 and status != 504:
        code, message, retryable = (
            "provider_unavailable",
            "Provider is temporarily unavailable",
            True,
        )
    wait = retry_seconds(retry_after) or retry_seconds(retry_delay_seconds)
    return AppError(
        code,
        message,
        503 if code == "provider_unavailable" else status if status in {429, 504} else 502,
        retryable,
        retry_after_seconds=wait,
        retry_time_source="provider" if wait is not None else None,
        pause=status == 429,
        failure_origin=origin,
        provider_status=status,
    )
