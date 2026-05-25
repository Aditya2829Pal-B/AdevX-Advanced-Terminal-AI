"""Tracing hooks for future OpenTelemetry integration."""

from __future__ import annotations

from contextlib import contextmanager
from time import perf_counter
from typing import Iterator

from adevx.telemetry.logger import StructuredLogger


@contextmanager
def trace_span(logger: StructuredLogger, name: str, **fields) -> Iterator[None]:
    start = perf_counter()
    logger.debug("span.start", span=name, **fields)
    try:
        yield
    finally:
        elapsed_ms = (perf_counter() - start) * 1000.0
        logger.debug("span.end", span=name, elapsed_ms=round(elapsed_ms, 2), **fields)

