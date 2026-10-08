"""Turns role-tagged spans into a string, with or without ANSI colors."""

from __future__ import annotations

import os
from collections.abc import Iterable

from rich.color import ColorSystem
from rich.errors import StyleSyntaxError
from rich.style import Style

from .colors import Theme
from .exceptions import ConfigError
from .models import Span


class Renderer:
    """Applies a :class:`Theme` to spans. Styles are resolved once, at construction, so
    rendering is just string concatenation. With ``color=False`` the output is plain text."""

    def __init__(self, theme: Theme, color: bool) -> None:
        self.color = color
        self._wrap: dict[str, tuple[str, str]] = {}
        if not color:
            return
        for role, style in theme.styles().items():
            if not style:
                continue
            try:
                sample = Style.parse(style).render("\0", color_system=ColorSystem.STANDARD)
            except StyleSyntaxError as exc:
                raise ConfigError(f"invalid style {style!r} for role {role!r}: {exc}") from exc
            head, _, tail = sample.partition("\0")
            if head:
                self._wrap[role] = (head, tail)

    def render(self, spans: Iterable[Span]) -> str:
        """Join ``spans`` into one string (may contain newlines, no trailing newline)."""
        if not self.color:
            return "".join(span.text for span in spans)
        wrap = self._wrap
        out: list[str] = []
        for text, role in spans:
            pair = wrap.get(role)
            out.append(f"{pair[0]}{text}{pair[1]}" if pair and text.strip() else text)
        return "".join(out)


def enable_windows_ansi() -> None:
    """Best effort: turn on ANSI escape processing for the Windows console (no-op elsewhere)."""
    if os.name != "nt":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
        for std_handle in (-11, -12):  # stdout, stderr
            handle = kernel32.GetStdHandle(std_handle)
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # pragma: no cover - purely cosmetic
        pass
