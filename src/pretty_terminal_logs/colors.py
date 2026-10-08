"""Themes (semantic styles) and color-capability detection.

No ANSI escape sequences live here: a :class:`Theme` only holds Rich style strings
(``"bold white on red"``); the renderer turns them into escape codes.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import TextIO

from .exceptions import ConfigError

_NON_STYLE_FIELDS = frozenset({"name", "layout"})


@dataclass(frozen=True)
class Theme:
    """Maps semantic roles to Rich style strings. An empty string means "no styling".

    ``layout`` is ``"block"`` (multi-line, the default) or ``"inline"`` (one line per entry).
    """

    name: str = "custom"
    debug: str = "dim"
    info: str = "cyan"
    warning: str = "yellow"
    error: str = "red"
    critical: str = "bold white on red"
    time: str = "dim"
    separator: str = "dim"
    module: str = "magenta"
    logger: str = "bold"
    message: str = ""
    context_key: str = "dim"
    context_value: str = "dim"
    identifier: str = "dim"
    raw: str = "dim"
    traceback: str = "dim"
    traceback_error: str = "bold red"
    layout: str = "block"

    def styles(self) -> dict[str, str]:
        """Return ``{role: style}`` for every styled role."""
        return {
            f.name: getattr(self, f.name) for f in fields(self) if f.name not in _NON_STYLE_FIELDS
        }


DEFAULT_THEME = Theme(name="default")

MINIMAL_THEME = Theme(
    name="minimal",
    debug="dim",
    info="",
    warning="yellow",
    error="red",
    critical="bold red",
    time="dim",
    separator="",
    module="",
    logger="",
    context_key="dim",
    context_value="dim",
    identifier="dim",
    raw="",
    traceback="",
    traceback_error="red",
    layout="inline",
)

HIGH_CONTRAST_THEME = Theme(
    name="high-contrast",
    debug="white",
    info="bold bright_cyan",
    warning="bold black on yellow",
    error="bold white on red",
    critical="bold bright_white on bright_red",
    time="bright_white",
    separator="bright_white",
    module="bold bright_magenta",
    logger="bold bright_white",
    message="bright_white",
    context_key="bold white",
    context_value="bright_white",
    identifier="white",
    raw="white",
    traceback="white",
    traceback_error="bold bright_red",
)

THEMES: dict[str, Theme] = {}


def _key(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def register_theme(theme: Theme) -> None:
    """Make ``theme`` selectable by name (``--theme``, config file, ``PRETTY_LOG_THEME``)."""
    THEMES[_key(theme.name)] = theme


for _theme in (DEFAULT_THEME, MINIMAL_THEME, HIGH_CONTRAST_THEME):
    register_theme(_theme)


def get_theme(name: str) -> Theme:
    """Look up a registered theme by name (case-insensitive, ``_`` and ``-`` interchangeable)."""
    try:
        return THEMES[_key(name)]
    except KeyError:
        available = ", ".join(sorted(THEMES))
        raise ConfigError(f"unknown theme {name!r} (available: {available})") from None


def should_use_color(
    setting: bool | None,
    stream: TextIO,
    env: Mapping[str, str] | None = None,
) -> bool:
    """Decide whether to emit ANSI colors.

    An explicit ``setting`` (True/False) always wins. Otherwise colors are on only for an
    interactive terminal, and off for pipes/redirects, CI, ``NO_COLOR`` and ``TERM=dumb``.
    """
    if setting is not None:
        return setting
    env = os.environ if env is None else env
    if env.get("NO_COLOR") or env.get("CI") or env.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    try:
        return bool(isatty and isatty())
    except ValueError:  # closed stream
        return False
