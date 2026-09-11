"""Structured logging configuration (stdlib logging + structlog)."""

from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure process-wide structured logging.

    Emits JSON logs in staging/production and human-readable logs locally.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[*shared_processors, structlog.processors.JSONRenderer()],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=numeric_level, format="%(message)s", force=True)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for the given name."""
    return structlog.get_logger(name)
