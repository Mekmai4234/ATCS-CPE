"""Measured mechanism timings, without transcripts, URLs, keys or exception text."""

import logging
from contextlib import contextmanager
from functools import wraps
from time import perf_counter

logger = logging.getLogger(__name__)


@contextmanager
def ingestion_stage(name):
    started, outcome = perf_counter(), "failed"
    try:
        yield
        outcome = "completed"
    finally:
        logger.info(
            "ingestion_stage stage=%s outcome=%s duration_ms=%.3f",
            name,
            outcome,
            max(0, (perf_counter() - started) * 1000),
        )


def timed_ingestion(name):
    def decorate(function):
        @wraps(function)
        async def measured(*args, **kwargs):
            with ingestion_stage(name):
                return await function(*args, **kwargs)

        return measured

    return decorate
