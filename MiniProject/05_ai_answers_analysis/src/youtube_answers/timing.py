"""Operational timings only; never record questions, answers, keys or exception text."""

import logging
from collections import Counter
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

logger = logging.getLogger(__name__)
_calls = ContextVar("answer_provider_calls", default=None)


def provider_call(operation):
    """Count actual dispatch attempts, never quota reservations or presumed successes."""
    counts = _calls.get()
    if counts is not None:
        counts[operation] += 1


def measured_operation(kind):
    def decorate(function):
        @wraps(function)
        async def measured(*args, **kwargs):
            counts = Counter()
            token = _calls.set(counts)
            started, outcome = perf_counter(), "failed"
            try:
                result = await function(*args, **kwargs)
                outcome = "completed"
                return result
            finally:
                _calls.reset(token)
                logger.info(
                    "answer_operation kind=%s outcome=%s duration_ms=%.3f "
                    "count_tokens_calls=%d generation_calls=%d",
                    kind,
                    outcome,
                    max(0, (perf_counter() - started) * 1000),
                    counts["count_tokens"],
                    counts["generate_content"],
                )

        return measured

    return decorate


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
