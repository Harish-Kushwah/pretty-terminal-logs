"""The ``pretty-log`` command: reads log lines (stdin, files, or ``--follow``) and renders them."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import TextIO

from . import __version__
from .colors import get_theme, should_use_color
from .config import Config, parse_level, resolve_config
from .exceptions import ConfigError
from .formatter import EntryFormatter, pick_glyphs
from .parser import StreamParser
from .renderer import Renderer, enable_windows_ansi

_LEVEL_NUMBERS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the ``pretty-log`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="pretty-log",
        description="Render application logs readably. Reads stdin when no file is given.",
        epilog="examples:  python app.py 2>&1 | pretty-log     "
        "pretty-log app.log     pretty-log --follow app.log",
    )
    parser.add_argument(
        "files", nargs="*", metavar="FILE", help="log file(s) to read (default: stdin)"
    )
    parser.add_argument("--version", action="version", version=f"pretty-log {__version__}")
    color = parser.add_mutually_exclusive_group()
    color.add_argument(
        "--color",
        dest="color",
        action="store_const",
        const=True,
        default=None,
        help="force colors on",
    )
    color.add_argument(
        "--no-color", dest="color", action="store_const", const=False, help="force colors off"
    )
    parser.add_argument("--config", metavar="FILE", help="YAML config file (e.g. pretty-log.yaml)")
    parser.add_argument("--theme", metavar="NAME", help="default, minimal or high-contrast")
    parser.add_argument("--level", metavar="LEVEL", help="hide entries below this level")
    parser.add_argument("--compact", action="store_true", default=None, help="one line per entry")
    parser.add_argument(
        "--verbose", action="store_true", default=None, help="include the date in timestamps"
    )
    parser.add_argument(
        "--no-short-ids",
        dest="shorten_ids",
        action="store_false",
        default=None,
        help="show full UUIDs",
    )
    parser.add_argument("-f", "--follow", metavar="FILE", help="follow FILE like tail -f")
    return parser


def _build_config(args: argparse.Namespace) -> Config:
    config = resolve_config(args.config)
    changes: dict[str, object] = {}
    if args.theme is not None:
        changes["theme"] = get_theme(args.theme).name
    if args.level is not None:
        changes["level"] = parse_level(args.level)
    for key in ("color", "compact", "verbose", "shorten_ids"):
        if getattr(args, key) is not None:
            changes[key] = getattr(args, key)
    return config.replace(**changes)


def read_stream(handle: TextIO) -> Iterator[str]:
    """Yield lines from a text stream as they arrive."""
    yield from handle


def read_files(paths: Sequence[str]) -> Iterator[str]:
    """Yield lines from each file in turn."""
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            yield from handle


def follow_file(
    path: str,
    poll_interval: float = 0.25,
    tail_lines: int = 10,
    should_stop: Callable[[], bool] = lambda: False,
) -> Iterator[str]:
    """Yield lines appended to ``path`` (like ``tail -f``), starting with the last ``tail_lines``.

    Partial lines are buffered until their newline arrives, and truncation / rotation
    (inode change) is handled by reopening from the start.
    """
    handle = open(path, "rb")  # noqa: SIM115 - closed in the finally block below
    try:
        size = os.fstat(handle.fileno()).st_size
        handle.seek(max(0, size - 65536))
        data = handle.read().decode("utf-8", errors="replace").splitlines(keepends=True)
        if size > 65536:
            data = data[1:]  # first line is probably cut off
        yield from data[-tail_lines:] if tail_lines > 0 else []
        pending = b""
        while not should_stop():
            chunk = handle.readline()
            if chunk:
                pending += chunk
                if pending.endswith(b"\n"):
                    yield pending.decode("utf-8", errors="replace")
                    pending = b""
                continue
            if _was_rotated(path, handle):
                if pending:
                    yield pending.decode("utf-8", errors="replace")
                    pending = b""
                handle.close()
                handle = _reopen(path, should_stop)
                if handle is None:
                    return
                continue
            time.sleep(poll_interval)
        if pending:
            yield pending.decode("utf-8", errors="replace")
    finally:
        if handle is not None:
            handle.close()


def _was_rotated(path: str, handle: object) -> bool:
    try:
        current = os.stat(path)
        opened = os.fstat(handle.fileno())  # type: ignore[attr-defined]
    except OSError:
        return False  # path briefly missing during rotation: keep waiting
    if current.st_size < handle.tell():  # type: ignore[attr-defined]
        return True  # truncated
    return bool(current.st_ino and opened.st_ino and current.st_ino != opened.st_ino)


def _reopen(path: str, should_stop: Callable[[], bool]):  # type: ignore[no-untyped-def]
    while not should_stop():
        try:
            return open(path, "rb")  # noqa: SIM115
        except OSError:
            time.sleep(0.1)
    return None


class _Pipeline:
    """parse -> level filter -> format -> render -> write, one line at a time."""

    def __init__(self, config: Config, out: TextIO, color: bool) -> None:
        theme = get_theme(config.theme)
        self.out = out
        self.min_level = config.level
        self.parser = StreamParser()
        self.formatter = EntryFormatter(config, theme, pick_glyphs(out))
        self.renderer = Renderer(theme, color)
        self._shown = True

    def run(self, lines: Iterable[str]) -> None:
        for line in lines:
            if not line.strip():
                continue
            entry = self.parser.parse(line)
            if entry.continuation:
                if not self._shown:
                    continue
            else:
                self._shown = self._passes(entry.level)
                if not self._shown:
                    continue
            self.out.write(self.renderer.render(self.formatter.format(entry)) + "\n")
            self.out.flush()

    def _passes(self, level: str) -> bool:
        if self.min_level is None or level == "RAW":
            return True
        return _LEVEL_NUMBERS.get(level, 0) >= self.min_level


def _use_utf8(stream: TextIO) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure:
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run the CLI and return the process exit code."""
    args = build_arg_parser().parse_args(argv)
    if stdin is None:
        stdin = sys.stdin
        _use_utf8(stdin)
    if stdout is None:
        stdout = sys.stdout
        _use_utf8(stdout)
    stderr = stderr or sys.stderr

    try:
        config = _build_config(args)
        color = should_use_color(config.color, stdout)
        pipeline = _Pipeline(config, stdout, color)
    except ConfigError as exc:
        print(f"pretty-log: error: {exc}", file=stderr)
        return 2
    if color:
        enable_windows_ansi()

    try:
        if args.follow:
            if args.files:
                print("pretty-log: error: --follow takes its file as the option value", file=stderr)
                return 2
            lines: Iterable[str] = follow_file(args.follow)
        elif args.files:
            lines = read_files(args.files)
        else:
            if stdin.isatty():
                print(
                    "pretty-log: error: no input; pipe logs in or pass a FILE (see --help)",
                    file=stderr,
                )
                return 2
            lines = read_stream(stdin)
        pipeline.run(lines)
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:  # downstream (e.g. `head`) closed early
        with contextlib.suppress(OSError, ValueError):
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except OSError as exc:
        print(
            f"pretty-log: error: {exc.filename or ''}: {exc.strerror or exc}".replace(": :", ":"),
            file=stderr,
        )
        return 1
    return 0


def console_main() -> None:
    """Entry point for the ``pretty-log`` script."""
    sys.exit(main())
