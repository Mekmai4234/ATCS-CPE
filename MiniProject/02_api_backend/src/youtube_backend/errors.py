class AppError(Exception):
    """Only application-owned, public messages may cross the API boundary."""

    def __init__(self, code: str, message: str, status_code: int = 400, retryable: bool = False):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(message)


class LeaseLost(Exception):
    """The current execution may no longer publish results."""
