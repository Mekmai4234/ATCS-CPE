from youtube_backend.errors import AppError


def error(code: str, message: str, *, retryable=False, status=409):
    return AppError(code, message, status, retryable)
