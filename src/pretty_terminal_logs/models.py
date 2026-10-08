"""Normalized data model shared by the parser, formatter and renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, NamedTuple

#: Fields promoted out of ``extra`` into first-class attributes of :class:`LogEntry`.
CONTEXT_FIELDS = ("trace_id", "user_id", "module", "api", "request_id")

#: Short/alternative spellings that map onto :data:`CONTEXT_FIELDS` when parsing text and JSON.
CONTEXT_ALIASES: dict[str, str] = {
    "t": "trace_id",
    "trace": "trace_id",
    "trace_id": "trace_id",
    "u": "user_id",
    "user": "user_id",
    "user_id": "user_id",
    "mod": "module",
    "module": "module",
    "api": "api",
    "req": "request_id",
    "req_id": "request_id",
    "request": "request_id",
    "request_id": "request_id",
}


class Span(NamedTuple):
    """A piece of output text tagged with a semantic *role* (e.g. ``"info"``, ``"module"``).

    The formatter emits spans; the renderer maps roles to styles via the active theme.
    """

    text: str
    role: str = "message"


@dataclass(slots=True)
class LogEntry:
    """A parsed, source-format-independent log record.

    ``None`` means "not present in the source"; ``""`` means "present but empty"
    (e.g. ``api=``). Both are hidden when rendering. Unrecognised ``key=value`` metadata
    lives in ``extra``.
    """

    timestamp: str | None = None
    level: str = "INFO"
    logger: str | None = None
    module: str | None = None
    message: str = ""
    trace_id: str | None = None
    user_id: str | None = None
    api: str | None = None
    request_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    exception: str | None = None
    #: True for an unparseable line that continues the previous record (e.g. a traceback frame).
    continuation: bool = False
