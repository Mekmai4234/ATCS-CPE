import math


class AppError(Exception):
    """Only application-owned, public messages may cross the API boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        retryable: bool = False,
        *,
        retry_after_seconds=None,
        retry_time_source=None,
        pause=False,
        failure_origin=None,
        provider_status=None,
    ):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        valid_wait = (
            type(retry_after_seconds) in {int, float}
            and math.isfinite(retry_after_seconds)
            and 0 < retry_after_seconds <= 86400
        )
        self.retry_after_seconds = retry_after_seconds if valid_wait else None
        self.retry_time_source = (
            retry_time_source if retry_time_source in {"provider", "estimate"} else None
        )
        self.pause = pause
        self.failure_origin = (
            failure_origin if failure_origin in {"http", "transport", "timeout"} else None
        )
        self.provider_status = (
            provider_status
            if self.failure_origin == "http"
            and type(provider_status) is int
            and 100 <= provider_status <= 599
            else None
        )
        super().__init__(message)


class LeaseLost(Exception):
    """The current execution may no longer publish results."""
