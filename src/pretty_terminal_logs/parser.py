"""Parsers that turn log lines into :class:`~pretty_terminal_logs.models.LogEntry`.

Each parser returns ``None`` when a line is not in its format; :class:`AutoParser` tries them
in turn and :func:`parse_line` / :class:`StreamParser` fall back to a RAW entry so that no
input line is ever dropped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any, Protocol

from .models import CONTEXT_ALIASES, LogEntry

LEVEL_ALIASES = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "WARN": "WARNING",
    "ERROR": "ERROR",
    "ERR": "ERROR",
    "CRITICAL": "CRITICAL",
    "FATAL": "CRITICAL",
}

_TS = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"

# "[INFO] [t=.. u=.. mod=.. api= req=] Logger - message"  /  "<ts> [INFO] message"
_BRACKET_RE = re.compile(rf"^(?:(?P<ts>{_TS})\s+)?\[(?P<level>[A-Za-z]+)\]\s*(?P<rest>.*)$")
# "<ts> INFO dashboard_report message"
_GENERIC_RE = re.compile(rf"^(?P<ts>{_TS})\s+(?:-\s+)?(?P<level>[A-Za-z]+)\s+(?P<rest>.*)$")

_KV_RE = re.compile(r"([A-Za-z_][\w.-]*)=(\S*)")
_DASH_RE = re.compile(r"^(?P<name>[A-Za-z_][\w.]*) - (?P<msg>.*)$")
_COLON_RE = re.compile(r"^(?P<name>[A-Za-z_][\w.]*): (?P<msg>.*)$")
_DOTTED_COLON_RE = re.compile(r"^(?P<name>[A-Za-z_]\w*(?:[._]\w+)+):\s+(?P<msg>.*)$")
_MODULE_RE = re.compile(r"^(?P<name>[a-z_]\w*(?:[._]\w+)+)(?::|\s+-)?\s+(?P<msg>\S.*)$")
# trailing "key=value, key=value" pairs at the end of a message
_TAIL_KV_RE = re.compile(r"(?:^|[\s,;])([A-Za-z_][\w.-]*)=([^\s,;]*)[\s,;.]*$")

# logging.basicConfig() default: "WARNING:root:message"
_BASIC_RE = re.compile(
    r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):(?P<name>[^:\s]+):(?P<msg>.*)$"
)
# uvicorn's default: "INFO:     Started server process [26112]"
_UVICORN_RE = re.compile(r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):\s{2,}(?P<msg>\S.*)$")
# "<ts> - name - LEVEL - message"  (common logging cookbook format)
_DASHED_RE = re.compile(
    rf"^(?P<ts>{_TS})\s+-\s+(?P<name>\S+)\s+-\s+(?P<level>[A-Za-z]+)\s+-\s+(?P<msg>.*)$"
)

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_TRACEBACK_START = "Traceback (most recent call last)"


class LogParser(Protocol):
    """Anything that can try to parse a single line."""

    def parse(self, line: str) -> LogEntry | None:
        """Return an entry, or ``None`` if the line is not in this parser's format."""
        ...


def strip_ansi(line: str) -> str:
    """Remove ANSI escape sequences (so already-colored input still parses)."""
    return _ANSI_RE.sub("", line) if "\x1b" in line else line


def clean_line(line: str) -> str:
    """Drop the line ending, a leading byte-order mark (Windows PowerShell pipes add one) and
    ANSI escapes."""
    return strip_ansi(line.rstrip("\r\n").removeprefix("\N{ZERO WIDTH NO-BREAK SPACE}"))


def normalize_level(value: object) -> str | None:
    """Map ``warn``/``Fatal``/... to a canonical level name; ``None`` if unknown."""
    if not isinstance(value, str):
        return None
    return LEVEL_ALIASES.get(value.strip().upper())


def _split_pairs(pairs: Iterable[tuple[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separate recognised context fields from arbitrary extras."""
    known: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in pairs:
        canonical = CONTEXT_ALIASES.get(key)
        if canonical:
            known[canonical] = value if isinstance(value, str) else str(value)
        else:
            extra[key] = value
    return known, extra


def _split_tail_kv(message: str) -> tuple[str, list[tuple[str, str]]]:
    """Peel trailing ``key=value`` pairs off ``message`` (``"x. a=1, b=2"`` -> ``"x"``, a, b)."""
    if "=" not in message:
        return message, []
    found: list[tuple[str, str]] = []
    while True:
        match = _TAIL_KV_RE.search(message)
        if not match or not message[: match.start()].strip():
            break
        found.append((match.group(1), match.group(2).rstrip(".")))
        message = message[: match.start()]
    if found:
        message = message.rstrip(" ,;.:")
        found.reverse()
    return message, found


class TextLogParser:
    """Parses the app format ``[LEVEL] [t=.. u=.. mod=..] Logger - message`` and common
    ``<timestamp> LEVEL [module] message`` text layouts."""

    def parse(self, line: str) -> LogEntry | None:
        if not line or not (line[0] == "[" or line[0].isdigit()):
            return None
        match = _BRACKET_RE.match(line)
        if match:
            entry = self._from_bracket(match)
            if entry:
                return entry
        match = _GENERIC_RE.match(line)
        if match:
            return self._from_generic(match)
        return None

    @staticmethod
    def _from_bracket(match: re.Match[str]) -> LogEntry | None:
        level = normalize_level(match["level"])
        if level is None:
            return None
        rest = match["rest"]
        pairs: list[tuple[str, str]] = []
        has_ctx = False
        if rest.startswith("["):
            end = rest.find("]")
            inner = rest[1:end] if end != -1 else ""
            if end != -1 and ("=" in inner or not inner.strip()):
                pairs = _KV_RE.findall(inner)
                has_ctx = True
                rest = rest[end + 1 :].lstrip()
        logger: str | None = None
        named = (_DASH_RE.match(rest) or _COLON_RE.match(rest)) if has_ctx else None
        named = named or _DOTTED_COLON_RE.match(rest)
        if named:
            logger, rest = named["name"], named["msg"]
        message, tail = _split_tail_kv(rest)
        known, extra = _split_pairs([*pairs, *tail])
        return LogEntry(
            timestamp=match["ts"], level=level, logger=logger, message=message, extra=extra, **known
        )

    @staticmethod
    def _from_generic(match: re.Match[str]) -> LogEntry | None:
        level = normalize_level(match["level"])
        if level is None:
            return None
        rest = match["rest"]
        module: str | None = None
        named = _MODULE_RE.match(rest)
        if named:
            module, rest = named["name"], named["msg"]
        message, tail = _split_tail_kv(rest)
        known, extra = _split_pairs(tail)
        known.setdefault("module", module)
        return LogEntry(timestamp=match["ts"], level=level, message=message, extra=extra, **known)


class PythonLogParser:
    """Parses output of Python's standard ``logging`` layouts (basicConfig default, and
    ``<asctime> - <name> - <level> - <message>``)."""

    def parse(self, line: str) -> LogEntry | None:
        if not line or not line[0].isalnum():
            return None
        match = _BASIC_RE.match(line) or _DASHED_RE.match(line)
        if not match:
            uvicorn = _UVICORN_RE.match(line)
            if uvicorn:
                return LogEntry(level=uvicorn["level"], logger="uvicorn", message=uvicorn["msg"])
            return None
        level = normalize_level(match["level"])
        if level is None:
            return None
        groups = match.groupdict()
        return LogEntry(
            timestamp=groups.get("ts"), level=level, logger=match["name"], message=match["msg"]
        )


_TS_KEYS = ("timestamp", "time", "ts", "@timestamp", "asctime", "datetime")
_LEVEL_KEYS = ("level", "levelname", "severity", "lvl", "log_level")
_MESSAGE_KEYS = ("message", "msg", "event")
_LOGGER_KEYS = ("logger", "logger_name", "name")
_EXC_KEYS = ("exception", "exc_info", "traceback", "stack_trace", "stack")


def _pop_first(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data:
            return data.pop(key)
    return None


def _format_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds).strftime("%Y-%m-%d %H:%M:%S")
        except (OverflowError, OSError, ValueError):
            return str(value)
    return str(value)


class JsonLogParser:
    """Parses one JSON object per line with common field names (``timestamp``, ``level``,
    ``message``/``msg``, ``logger``, ...); everything else is kept in ``extra``."""

    def parse(self, line: str) -> LogEntry | None:
        text = line.strip()
        if not (text.startswith("{") and text.endswith("}")):
            return None
        try:
            obj = json.loads(text)
        except ValueError:
            return None
        if not isinstance(obj, dict):
            return None
        data: dict[str, Any] = dict(obj)
        timestamp = _pop_first(data, _TS_KEYS)
        level = _pop_first(data, _LEVEL_KEYS)
        message = _pop_first(data, _MESSAGE_KEYS)
        logger = _pop_first(data, _LOGGER_KEYS)
        exception = _pop_first(data, _EXC_KEYS)
        if level is None and message is None:
            return None
        known, extra = _split_pairs(data.items())
        return LogEntry(
            timestamp=_format_timestamp(timestamp),
            level=normalize_level(level) or str(level or "INFO").upper(),
            logger=None if logger is None else str(logger),
            message="" if message is None else str(message),
            extra=extra,
            exception=None if exception is None else str(exception),
            **known,
        )


class AutoParser:
    """Tries JSON, then text, then Python-logging formats."""

    def __init__(self, parsers: Iterable[LogParser] | None = None) -> None:
        self._json = JsonLogParser()
        self._parsers: tuple[LogParser, ...] = (
            tuple(parsers) if parsers is not None else (TextLogParser(), PythonLogParser())
        )

    def parse(self, line: str) -> LogEntry | None:
        if line.startswith("{"):
            entry = self._json.parse(line)
            if entry:
                return entry
        for parser in self._parsers:
            entry = parser.parse(line)
            if entry:
                return entry
        return None


_AUTO = AutoParser()


def parse_line(line: str) -> LogEntry:
    """Parse ``line`` with any known format; unparseable lines become a RAW entry."""
    line = clean_line(line)
    return _AUTO.parse(line) or LogEntry(level="RAW", message=line)


class StreamParser:
    """Stateful line-by-line parser that keeps tracebacks and indented follow-up lines attached
    (as ``continuation`` entries) to the record they belong to, without any lookahead, so it is
    safe for ``tail -f``-style streaming."""

    def __init__(self, parser: LogParser | None = None) -> None:
        self._parser: LogParser = parser or _AUTO
        self._seen_any = False
        self._in_traceback = False

    def parse(self, line: str) -> LogEntry:
        line = clean_line(line)
        entry = self._parser.parse(line)
        if entry is not None:
            self._seen_any = True
            self._in_traceback = False
            return entry

        continuation = False
        if line.startswith(_TRACEBACK_START):
            self._in_traceback = True
            continuation = self._seen_any
        elif self._in_traceback:
            continuation = True
            if not line[:1].isspace():  # the final "SomeError: message" line
                self._in_traceback = False
        elif line[:1].isspace() and self._seen_any:
            continuation = True
        self._seen_any = True
        return LogEntry(level="RAW", message=line, continuation=continuation)
