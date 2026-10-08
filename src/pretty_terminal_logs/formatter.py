"""Layout of a :class:`LogEntry` into role-tagged spans, plus the stdlib ``logging`` integration."""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, TextIO

from .colors import Theme, get_theme, should_use_color
from .config import Config, parse_color, parse_level, resolve_config
from .context import RECORD_ATTR, get_context
from .models import CONTEXT_FIELDS, LogEntry, Span
from .renderer import Renderer, enable_windows_ansi

_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}")
_CLOCK_RE = re.compile(r"(?:(\d{4}-\d{2}-\d{2})[T ])?(\d{2}:\d{2}:\d{2})")
_LABELS = {"trace_id": "trace", "user_id": "user", "request_id": "req"}
_LEVEL_ROLES = {
    "DEBUG": "debug",
    "INFO": "info",
    "WARNING": "warning",
    "ERROR": "error",
    "CRITICAL": "critical",
    "RAW": "raw",
}
_LEVEL_WIDTH = 8
_HANDLER_NAME = "pretty_terminal_logs"


@dataclass(frozen=True)
class Glyphs:
    """Box-drawing characters used by the block layout."""

    bar: str
    branch: str


UNICODE_GLYPHS = Glyphs(bar="│", branch="└─")
ASCII_GLYPHS = Glyphs(bar="|", branch="`-")


def pick_glyphs(stream: TextIO) -> Glyphs:
    """Use Unicode box characters if ``stream`` can encode them, otherwise ASCII."""
    try:
        "│└─".encode(getattr(stream, "encoding", None) or "utf-8")
    except (UnicodeEncodeError, LookupError):
        return ASCII_GLYPHS
    return UNICODE_GLYPHS


def shorten_uuid(value: str) -> str:
    """``d8be77d2-2375-4b71-a818-b676cd5e80da`` -> ``d8be77d2...80da``; other strings unchanged."""
    if _UUID_RE.fullmatch(value):
        return f"{value[:8]}...{value[-4:]}"
    return value


class EntryFormatter:
    """Lays out a :class:`LogEntry` as spans. Knows nothing about colors or I/O."""

    def __init__(self, config: Config, theme: Theme | None = None, glyphs: Glyphs = UNICODE_GLYPHS):
        self.config = config
        self.glyphs = glyphs
        theme = theme or get_theme(config.theme)
        self._inline = config.compact or theme.layout == "inline"
        self._ts_width = 19 if config.verbose else 8
        self._placeholder = "-" * 10 + " --:--:--" if config.verbose else "--:--:--"

    def format(self, entry: LogEntry) -> list[Span]:
        """Return the spans (including embedded newlines) for ``entry``."""
        if entry.continuation:
            return self._continuation(entry)
        return self._inline_layout(entry) if self._inline else self._block_layout(entry)

    # -- pieces ---------------------------------------------------------------------------

    def _clock(self, entry: LogEntry) -> str:
        match = _CLOCK_RE.search(entry.timestamp) if entry.timestamp else None
        if not match:
            return self._placeholder
        date, clock = match.groups()
        if not self.config.verbose:
            return clock
        return f"{date or '-' * 10} {clock}"

    def _value(self, value: Any) -> tuple[str, str]:
        text = str(value)
        if self.config.shorten_ids:
            short = shorten_uuid(text)
            if short != text:
                return short, "identifier"
        return text, "context_value"

    def _context_items(
        self, entry: LogEntry
    ) -> tuple[list[tuple[str, Any]], list[tuple[str, Any]]]:
        """Split metadata into configured context fields and the remaining extras."""
        wanted = self.config.context_fields
        fields: list[tuple[str, Any]] = []
        for name in wanted:
            value = getattr(entry, name) if name in CONTEXT_FIELDS else entry.extra.get(name)
            if value not in (None, ""):
                fields.append((_LABELS.get(name, name), value))
        extras = [
            (key, value)
            for key, value in entry.extra.items()
            if key not in wanted and value not in (None, "")
        ]
        return fields, extras

    def _pair(self, key: str, value: Any) -> list[Span]:
        text, role = self._value(value)
        return [Span(key, "context_key"), Span("=", "context_key"), Span(text, role)]

    def _traceback_lines(self, entry: LogEntry) -> list[list[Span]]:
        if not entry.exception:
            return []
        lines = entry.exception.strip("\n").splitlines()
        last = max((i for i, line in enumerate(lines) if line.strip()), default=-1)
        return [
            [Span(line, "traceback_error" if i == last else "traceback")]
            for i, line in enumerate(lines)
        ]

    # -- layouts --------------------------------------------------------------------------

    def _block_layout(self, entry: LogEntry) -> list[Span]:
        cfg, bar = self.config, self.glyphs.bar
        raw = entry.level == "RAW"
        sep = f" {bar} "
        spans: list[Span] = []
        indent = ""
        if cfg.show_timestamp:
            clock = self._clock(entry)
            spans += [Span(clock, "time"), Span(sep, "separator")]
            indent = " " * (len(clock) + 2)
        module = entry.module if cfg.show_module and not raw else None
        role = _LEVEL_ROLES.get(entry.level, "message")
        spans.append(Span(entry.level.ljust(_LEVEL_WIDTH) if module else entry.level, role))
        if module:
            spans += [Span(sep, "separator"), Span(module, "module")]

        body: list[list[Span]] = []
        if raw:
            body += [[Span(line, "raw")] for line in entry.message.splitlines()]
        else:
            if cfg.show_logger and entry.logger:
                body.append([Span(entry.logger, "logger")])
            body += [[Span(line, "message")] for line in entry.message.splitlines()]
            if cfg.show_context:
                fields, extras = self._context_items(entry)
                if fields:
                    line: list[Span] = []
                    for key, value in fields:
                        if line:
                            line.append(Span(sep, "separator"))
                        line += self._pair(key, value)
                    body.append(line)
                body += [self._pair(key, value) for key, value in extras]
        body += self._traceback_lines(entry)

        for i, line in enumerate(body):
            prefix = f"{indent}{self.glyphs.branch} " if i == 0 else f"{indent}   "
            spans += [Span("\n", "message"), Span(prefix, "separator"), *line]
        return spans

    def _inline_layout(self, entry: LogEntry) -> list[Span]:
        cfg = self.config
        raw = entry.level == "RAW"
        spans: list[Span] = []
        indent = ""
        if cfg.show_timestamp:
            clock = self._clock(entry)
            spans += [Span(clock, "time"), Span(" ", "message")]
            indent = " " * (len(clock) + 1)
        spans.append(Span(entry.level, _LEVEL_ROLES.get(entry.level, "message")))
        if cfg.show_module and entry.module and not raw:
            spans += [Span(" ", "message"), Span(entry.module, "module")]
        if cfg.show_logger and entry.logger and not raw:
            spans += [Span(" ", "message"), Span(f"{entry.logger}:", "logger")]
        lines = entry.message.splitlines() or [""]
        spans += [Span(" ", "message"), Span(lines[0], "raw" if raw else "message")]
        if cfg.show_context and not raw:
            fields, extras = self._context_items(entry)
            for key, value in [*fields, *extras]:
                spans += [Span(" ", "message"), *self._pair(key, value)]
        for line in lines[1:]:
            spans += [Span(f"\n{indent}", "message"), Span(line, "raw" if raw else "message")]
        for line_spans in self._traceback_lines(entry):
            spans += [Span(f"\n{indent}", "message"), *line_spans]
        return spans

    def _continuation(self, entry: LogEntry) -> list[Span]:
        if self._inline:
            indent = " " * (self._ts_width + 1) if self.config.show_timestamp else ""
            return [Span(indent + entry.message, "raw")]
        indent = " " * (self._ts_width + 2) if self.config.show_timestamp else ""
        return [Span(f"{indent}   {entry.message}", "raw")]


# -- stdlib logging integration ----------------------------------------------------------

_STD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def record_to_entry(
    record: logging.LogRecord,
    exception: str | None = None,
    aliases: Mapping[str, str] | None = None,
    hide: Collection[str] = (),
) -> LogEntry:
    """Convert a :class:`logging.LogRecord` (plus active context) into a :class:`LogEntry`.

    ``aliases`` maps record attribute names onto entry fields (e.g. ``{"module_name": "module"}``)
    and ``hide`` lists record attributes to leave out entirely.
    """
    merged: dict[str, Any] = dict(get_context())
    bound = record.__dict__.get(RECORD_ATTR)
    if bound:
        merged.update(bound)
    for key, value in record.__dict__.items():
        if key not in _STD_ATTRS and key != RECORD_ATTR:
            merged[key] = value
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in merged.items():
        if key in hide:
            continue
        if aliases:
            key = aliases.get(key, key)
        if key in CONTEXT_FIELDS:
            known[key] = None if value is None else str(value)
        else:
            extra[key] = value
    known.setdefault("module", record.module)
    return LogEntry(
        timestamp=_timestamp(record.created),
        level=record.levelname.upper(),
        logger=record.name,
        message=record.getMessage(),
        extra=extra,
        exception=exception,
        **known,
    )


_ts_cache: tuple[int, str] = (0, "")


def _timestamp(created: float) -> str:
    global _ts_cache
    second = int(created)
    cached_second, text = _ts_cache
    if cached_second != second:
        text = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(second))
        _ts_cache = (second, text)
    return text


class PrettyFormatter(logging.Formatter):
    """A :class:`logging.Formatter` producing the pretty block/inline layout.

    Works with any handler. Pass ``color=True`` to emit ANSI colors. For applications that
    already stamp their own attributes on records, ``aliases`` maps those attribute names to
    entry fields (``{"module_name": "module"}``) and ``hide`` drops attributes from the output.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        color: bool = False,
        glyphs: Glyphs = UNICODE_GLYPHS,
        aliases: Mapping[str, str] | None = None,
        hide: Collection[str] = (),
    ) -> None:
        super().__init__()
        self._aliases = dict(aliases) if aliases else None
        self._hide = frozenset(hide)
        self.config = config or Config()
        theme = get_theme(self.config.theme)
        self._layout = EntryFormatter(self.config, theme, glyphs)
        self._renderer = Renderer(theme, color)

    def format(self, record: logging.LogRecord) -> str:
        exception: str | None = None
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
            exception = record.exc_text
        if record.stack_info:
            stack = self.formatStack(record.stack_info)
            exception = f"{exception}\n{stack}" if exception else stack
        entry = record_to_entry(record, exception, self._aliases, self._hide)
        return self._renderer.render(self._layout.format(entry))


def setup_logging(
    level: int | str | None = None,
    color: bool | str | None = None,
    show_timestamp: bool | None = None,
    show_module: bool | None = None,
    show_context: bool | None = None,
    shorten_ids: bool | None = None,
    *,
    show_logger: bool | None = None,
    theme: str | None = None,
    compact: bool | None = None,
    stream: TextIO | None = None,
    config_file: str | os.PathLike[str] | None = None,
    force: bool = False,
) -> logging.Handler:
    """Install a pretty handler on the root logger and return it.

    Existing ``logging.getLogger(...).info(...)`` calls are untouched. Unset arguments fall
    back to ``PRETTY_LOG_*`` environment variables, then ``config_file`` (if any), then
    defaults. ``color=None``/``"auto"`` detects terminal support. Calling it again replaces the
    previous pretty handler; ``force=True`` also removes other root handlers.
    """
    config = resolve_config(config_file)
    overrides: dict[str, Any] = {
        "show_timestamp": show_timestamp,
        "show_module": show_module,
        "show_context": show_context,
        "shorten_ids": shorten_ids,
        "show_logger": show_logger,
        "compact": compact,
    }
    changes = {key: value for key, value in overrides.items() if value is not None}
    if level is not None:
        changes["level"] = parse_level(level)
    if color is not None:
        changes["color"] = parse_color(color)
    if theme is not None:
        changes["theme"] = get_theme(theme).name
    config = config.replace(**changes)

    stream = stream or sys.stderr
    use_color = should_use_color(config.color, stream)
    if use_color:
        enable_windows_ansi()
    handler = logging.StreamHandler(stream)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(PrettyFormatter(config, color=use_color, glyphs=pick_glyphs(stream)))

    root = logging.getLogger()
    for existing in list(root.handlers):
        if force or existing.get_name() == _HANDLER_NAME:
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(config.level if config.level is not None else logging.INFO)
    return handler
