"""Structured logging — structlog when available, stdlib JSON fallback otherwise.

The fallback exists so the package imports cleanly even in environments where
structlog hasn't been installed (e.g. running `adk web` from a global Python
that didn't `uv sync` our deps). Tools/agent code uses kwargs:

    logger.info("event.name", agent="x", count=3)

Either backend handles that signature.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

try:  # pragma: no cover — exercised on machines that have structlog
    import structlog

    _HAS_STRUCTLOG = True
except ImportError:
    _HAS_STRUCTLOG = False


def configure_logging(level: str = "INFO") -> None:
    """Configure JSON logging. Idempotent."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    if _HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )


class _StdlibJsonAdapter:
    """Minimal kwargs-aware JSON logger backed by stdlib `logging`.

    Mirrors the structlog API surface we actually use (`info`, `warning`,
    `error`, `bind`). Output goes to stdout as one JSON object per line so
    Cloud Logging picks it up the same way as structlog.
    """

    def __init__(self, name: str, bound: dict[str, Any] | None = None) -> None:
        self._name = name
        self._bound: dict[str, Any] = bound or {}
        self._logger = logging.getLogger(name)

    def bind(self, **kwargs: Any) -> _StdlibJsonAdapter:
        merged = {**self._bound, **kwargs}
        return _StdlibJsonAdapter(self._name, merged)

    def _emit(self, level: int, event: str, **kwargs: Any) -> None:
        if not self._logger.isEnabledFor(level):
            return
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": logging.getLevelName(level).lower(),
            "logger": self._name,
            "event": event,
            **self._bound,
            **kwargs,
        }
        self._logger.log(level, json.dumps(payload, default=str))

    def debug(self, event: str, **kw: Any) -> None:
        self._emit(logging.DEBUG, event, **kw)

    def info(self, event: str, **kw: Any) -> None:
        self._emit(logging.INFO, event, **kw)

    def warning(self, event: str, **kw: Any) -> None:
        self._emit(logging.WARNING, event, **kw)

    def error(self, event: str, **kw: Any) -> None:
        self._emit(logging.ERROR, event, **kw)

    def exception(self, event: str, **kw: Any) -> None:
        self._emit(logging.ERROR, event, **kw)


def get_logger(name: str | None = None) -> Any:
    """Return a structured logger. structlog when present, JSON-stdlib otherwise."""
    if _HAS_STRUCTLOG:
        return structlog.get_logger(name)
    return _StdlibJsonAdapter(name or __name__)
