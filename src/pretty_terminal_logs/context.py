"""Contextual metadata for log records, built on :mod:`contextvars` (thread- and async-safe).

Nothing here is required: plain ``logging.getLogger(__name__)`` keeps working. Context set
with :func:`set_context` / :func:`log_context` is attached to every record emitted by a
logger configured through :func:`~pretty_terminal_logs.setup_logging`.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

#: LogRecord attribute used by :class:`ContextLogger` to carry its bound context.
RECORD_ATTR = "pretty_context"

_EMPTY: Mapping[str, Any] = MappingProxyType({})
_context: ContextVar[Mapping[str, Any]] = ContextVar("pretty_terminal_logs_context", default=_EMPTY)


def get_context() -> Mapping[str, Any]:
    """Return the current (read-only) context mapping."""
    return _context.get()


def set_context(**fields: Any) -> None:
    """Merge ``fields`` into the context of the current thread / async task."""
    _context.set({**_context.get(), **fields})


def clear_context() -> None:
    """Remove all context for the current thread / async task."""
    _context.set(_EMPTY)


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Temporarily add ``fields`` to the context; the previous context is restored on exit."""
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


class ContextLogger(logging.LoggerAdapter):  # type: ignore[type-arg]
    """A logger that attaches fixed context to every record. See :func:`get_context_logger`."""

    def __init__(self, logger: logging.Logger, context: Mapping[str, Any]) -> None:
        super().__init__(logger, dict(context))

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> tuple[Any, MutableMapping[str, Any]]:
        extra = dict(kwargs.get("extra") or {})
        extra[RECORD_ATTR] = self.extra
        kwargs["extra"] = extra
        return msg, kwargs

    def bind(self, **fields: Any) -> ContextLogger:
        """Return a new logger with additional context."""
        return ContextLogger(self.logger, {**(self.extra or {}), **fields})


def get_context_logger(name: str | None = None, **context: Any) -> ContextLogger:
    """Get a logger that automatically attaches ``context`` (e.g. ``trace_id``, ``user_id``,
    ``module``) to every record. Optional: ordinary ``logging.getLogger`` works too."""
    return ContextLogger(logging.getLogger(name), context)
