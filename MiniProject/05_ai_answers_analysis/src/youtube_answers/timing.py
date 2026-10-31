"""Operational timings only; never record questions, answers, keys or exception text."""

import logging
from functools import wraps
from time import perf_counter

logger = logging.getLogger(__name__)


def timed_stage(stage):
    def decorate(function):
        @wraps(function)
        async def measured(*args, **kwargs):
            started, outcome = perf_counter(), "failed"
            try:
                result = await function(*args, **kwargs)
                outcome = "completed"
                return result
            finally:
                logger.info(
                    "answer_stage stage=%s outcome=%s duration_ms=%.3f",
                    stage,
                    outcome,
                    max(0, (perf_counter() - started) * 1000),
                )

        return measured

    return decorate
