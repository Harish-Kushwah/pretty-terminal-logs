import pytest

from pretty_terminal_logs.colors import (
    DEFAULT_THEME,
    Theme,
    get_theme,
    register_theme,
    should_use_color,
)
from pretty_terminal_logs.exceptions import ConfigError
from pretty_terminal_logs.models import Span
from pretty_terminal_logs.renderer import Renderer


class FakeStream:
    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty


def test_plain_rendering_has_no_escape_codes():
    out = Renderer(DEFAULT_THEME, color=False).render(
        [Span("a", "info"), Span("\n"), Span("b", "error")]
    )
    assert out == "a\nb"


def test_colored_rendering_wraps_roles():
    out = Renderer(DEFAULT_THEME, color=True).render([Span("INFO", "info"), Span(" x", "message")])
    assert out == "\x1b[36mINFO\x1b[0m x"


def test_critical_is_bold_white_on_red():
    out = Renderer(DEFAULT_THEME, color=True).render([Span("CRITICAL", "critical")])
    assert out.startswith("\x1b[1;37;41m")


def test_invalid_style_raises_config_error():
    with pytest.raises(ConfigError):
        Renderer(Theme(name="bad", info="not-a-real-style-xyz"), color=True)


def test_themes_available_and_extensible():
    assert get_theme("default").layout == "block"
    assert get_theme("minimal").layout == "inline"
    assert get_theme("High_Contrast").name == "high-contrast"
    register_theme(Theme(name="mine", info="green"))
    assert get_theme("mine").info == "green"
    with pytest.raises(ConfigError, match="unknown theme"):
        get_theme("nope")


def test_color_explicit_setting_wins():
    assert should_use_color(True, FakeStream(False), {"NO_COLOR": "1", "CI": "1"}) is True
    assert should_use_color(False, FakeStream(True), {}) is False


def test_color_auto_detection():
    assert should_use_color(None, FakeStream(True), {}) is True
    assert should_use_color(None, FakeStream(False), {}) is False  # pipe / redirect
    assert should_use_color(None, FakeStream(True), {"NO_COLOR": "1"}) is False
    assert should_use_color(None, FakeStream(True), {"CI": "true"}) is False
    assert should_use_color(None, FakeStream(True), {"TERM": "dumb"}) is False
    assert should_use_color(None, object(), {}) is False  # no isatty()
