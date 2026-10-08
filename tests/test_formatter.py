import logging
import sys

from pretty_terminal_logs.colors import get_theme
from pretty_terminal_logs.config import Config
from pretty_terminal_logs.formatter import (
    ASCII_GLYPHS,
    EntryFormatter,
    PrettyFormatter,
    shorten_uuid,
)
from pretty_terminal_logs.models import LogEntry
from pretty_terminal_logs.renderer import Renderer

TRACE = "d8be77d2-2375-4b71-a818-b676cd5e80da"
USER = "22e2604a-b1e1-40c5-83b8-27312f6bcb71"


def entry(**kw):
    base = {
        "timestamp": "2026-10-07 15:44:12",
        "level": "INFO",
        "logger": "DashboardReportRepository",
        "module": "dashboard_report",
        "message": "Fetching data",
        "trace_id": TRACE,
        "user_id": USER,
        "api": "",
        "request_id": "",
    }
    base.update(kw)
    return LogEntry(**base)


def render(e, config=None, color=False, theme=None):
    config = config or Config()
    theme = get_theme(theme or config.theme)
    return Renderer(theme, color).render(EntryFormatter(config, theme).format(e))


def test_block_layout_matches_spec():
    assert render(entry()) == (
        "15:44:12 │ INFO     │ dashboard_report\n"
        "          └─ DashboardReportRepository\n"
        "             Fetching data\n"
        "             trace=d8be77d2...80da │ user=22e2604a...cb71"
    )


def test_extras_each_on_own_line_and_empty_values_hidden():
    out = render(
        entry(level="WARNING", trace_id=None, user_id=None, extra={"timeout": "361.2s", "x": ""})
    )
    assert out.splitlines()[-1] == "             timeout=361.2s"
    assert "x=" not in out
    assert "api=" not in out


def test_uuid_shortening_toggle():
    assert "trace=d8be77d2...80da" in render(entry())
    assert f"trace={TRACE}" in render(entry(), Config(shorten_ids=False))


def test_only_uuids_are_shortened():
    assert shorten_uuid(TRACE) == "d8be77d2...80da"
    assert shorten_uuid("abcdefghijklmnopqrstuvwxyz") == "abcdefghijklmnopqrstuvwxyz"
    out = render(entry(trace_id="not-a-uuid-but-long-identifier", message=TRACE))
    assert "trace=not-a-uuid-but-long-identifier" in out
    assert TRACE in out  # message text is never shortened


def test_timestamp_module_logger_context_toggles():
    cfg = Config(show_timestamp=False, show_module=False, show_logger=False, show_context=False)
    assert render(entry(), cfg) == "INFO\n└─ Fetching data"


def test_missing_timestamp_uses_placeholder():
    assert render(entry(timestamp=None)).startswith("--:--:-- │ INFO")


def test_verbose_includes_date():
    assert render(entry(), Config(verbose=True)).startswith("2026-10-07 15:44:12 │ INFO")


def test_custom_context_fields():
    out = render(entry(extra={"service": "api"}), Config(context_fields=("service", "trace_id")))
    assert out.splitlines()[-1].strip() == "service=api │ trace=d8be77d2...80da"


def test_multiline_message_is_indented():
    out = render(entry(message="line1\nline2", trace_id=None, user_id=None))
    assert out.splitlines()[-2:] == ["             line1", "             line2"]


def test_raw_entry():
    out = render(LogEntry(level="RAW", message="original log line"))
    assert out == "--:--:-- │ RAW\n          └─ original log line"


def test_continuation_entry_is_indented_under_previous():
    out = render(LogEntry(level="RAW", message='  File "x.py"', continuation=True))
    assert out == "             " + '  File "x.py"'


def test_minimal_theme_is_one_line():
    out = render(entry(trace_id=None, user_id=None, logger=None), theme="minimal")
    assert out == "15:44:12 INFO dashboard_report Fetching data"


def test_compact_flag_forces_inline():
    out = render(entry(), Config(compact=True))
    assert "\n" not in out
    assert out.startswith("15:44:12 INFO dashboard_report DashboardReportRepository: Fetching data")
    assert "trace=d8be77d2...80da" in out


def test_exception_in_entry_is_rendered_and_last_line_highlighted():
    e = entry(
        level="ERROR",
        exception="Traceback (most recent call last):\n  File \"a.py\"\nKeyError: 'x'",
    )
    plain = render(e)
    assert "Traceback (most recent call last):" in plain and "KeyError: 'x'" in plain
    colored = render(e, color=True)
    assert "\x1b[1;31mKeyError: 'x'" in colored


def test_colors_enabled_vs_disabled():
    plain, colored = render(entry()), render(entry(), color=True)
    assert "\x1b" not in plain
    assert "\x1b[36mINFO" in colored
    assert colored.replace("\x1b[0m", "").count("\x1b[") > 3
    import re

    assert re.sub(r"\x1b\[[0-9;]*m", "", colored) == plain


def test_ascii_glyph_fallback():
    out = EntryFormatter(Config(), glyphs=ASCII_GLYPHS).format(entry())
    text = Renderer(get_theme("default"), False).render(out)
    assert "│" not in text and "└" not in text and "|" in text


# -- logging.Formatter integration -------------------------------------------------------


def make_record(msg="hello", level=logging.INFO, exc_info=None, **extra):
    record = logging.getLogger("my.app").makeRecord(
        "my.app", level, __file__, 1, msg, (), exc_info, extra=extra
    )
    return record


def test_pretty_formatter_basic_record():
    out = PrettyFormatter().format(make_record("Application started"))
    lines = out.splitlines()
    assert lines[0].count("│") == 2 and "INFO" in lines[0] and lines[0].endswith("test_formatter")
    assert lines[1].strip() == "└─ my.app"
    assert lines[2].strip() == "Application started"


def test_pretty_formatter_message_args_and_extra():
    record = logging.getLogger("a").makeRecord(
        "a",
        logging.WARNING,
        "f.py",
        1,
        "n=%d",
        (3,),
        None,
        extra={"duration": "12ms", "trace_id": "t1"},
    )
    out = PrettyFormatter().format(record)
    assert "n=3" in out and "duration=12ms" in out and "trace=t1" in out


def test_pretty_formatter_exception():
    try:
        raise TimeoutError("connection timed out")
    except TimeoutError:
        record = make_record("Database operation failed", logging.ERROR, exc_info=sys.exc_info())
    out = PrettyFormatter().format(record)
    assert "Database operation failed" in out
    assert "Traceback (most recent call last):" in out
    assert "TimeoutError: connection timed out" in out
    assert "test_formatter.py" in out  # traceback info is not lost


def test_pretty_formatter_color_flag():
    assert "\x1b[" not in PrettyFormatter(color=False).format(make_record())
    assert "\x1b[" in PrettyFormatter(color=True).format(make_record())


def test_aliases_and_hide_for_apps_that_stamp_their_own_attributes():
    record = make_record(
        "Fetching",
        module_name="dashboard_report",
        api_name="GET /v1/x",
        tenant_id="t1",
        span_id="deadbeef",
    )
    formatter = PrettyFormatter(
        Config(show_logger=False, context_fields=("tenant_id", "api")),
        aliases={"module_name": "module", "api_name": "api"},
        hide={"span_id"},
    )
    out = formatter.format(record)
    assert out.splitlines()[0].endswith("│ dashboard_report")
    assert "tenant_id=t1 │ api=GET /v1/x" in out
    assert "span_id" not in out and "module_name" not in out
