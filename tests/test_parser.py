import pytest

from pretty_terminal_logs.parser import (
    JsonLogParser,
    PythonLogParser,
    StreamParser,
    TextLogParser,
    parse_line,
)

TRACE = "d8be77d2-2375-4b71-a818-b676cd5e80da"
USER = "22e2604a-b1e1-40c5-83b8-27312f6bcb71"
APP_LINE = (
    f"[INFO] [t={TRACE} u={USER} mod=dashboard_report api= req=] "
    "DashboardReportRepository - Fetching from v_material_with_chemical_and_msds_compliance"
)


def test_app_format_from_spec():
    entry = parse_line(APP_LINE)
    assert entry.level == "INFO"
    assert entry.trace_id == TRACE
    assert entry.user_id == USER
    assert entry.module == "dashboard_report"
    assert entry.api == ""
    assert entry.request_id == ""
    assert entry.logger == "DashboardReportRepository"
    assert entry.message == "Fetching from v_material_with_chemical_and_msds_compliance"
    assert entry.extra == {}


@pytest.mark.parametrize(
    ("level_in", "level_out"),
    [
        ("DEBUG", "DEBUG"),
        ("INFO", "INFO"),
        ("WARNING", "WARNING"),
        ("WARN", "WARNING"),
        ("ERROR", "ERROR"),
        ("CRITICAL", "CRITICAL"),
        ("FATAL", "CRITICAL"),
        ("info", "INFO"),
    ],
)
def test_levels(level_in, level_out):
    entry = parse_line(f"[{level_in}] [t=a u=b mod=m api= req=] Logger - hello")
    assert entry.level == level_out
    assert entry.message == "hello"


def test_trailing_key_values_become_extra():
    line = (
        "[WARNING] [t=a u=b mod=utils api= req=] AsyncTaskVisibilityController: extended "
        "visibility. old_id=7fe0, new_id=7fe1, timeout=361.2s"
    )
    entry = parse_line(line)
    assert entry.logger == "AsyncTaskVisibilityController"
    assert entry.message == "extended visibility"
    assert entry.extra == {"old_id": "7fe0", "new_id": "7fe1", "timeout": "361.2s"}


def test_arbitrary_metadata_preserved():
    entry = parse_line(
        "[INFO] [t=a mod=m] App - Started service=api environment=production host=server-01"
    )
    assert entry.message == "Started"
    assert entry.extra == {"service": "api", "environment": "production", "host": "server-01"}


def test_unknown_context_keys_go_to_extra():
    entry = parse_line("[INFO] [t=a region=eu mod=m] App - hi")
    assert entry.trace_id == "a"
    assert entry.extra == {"region": "eu"}


def test_missing_fields_are_none():
    entry = parse_line("[INFO] [t=a] App - hi")
    assert entry.user_id is None
    assert entry.module is None


def test_empty_context_bracket():
    entry = parse_line("[ERROR] [] Repo - failed")
    assert entry.level == "ERROR"
    assert entry.logger == "Repo"
    assert entry.trace_id is None


def test_message_that_is_only_key_values_is_kept():
    entry = parse_line("[INFO] [t=a] App - a=1")
    assert entry.message == "a=1"
    assert entry.extra == {}


def test_generic_timestamp_level_module():
    entry = parse_line("2026-10-07 15:44:12 INFO dashboard_report Fetching data")
    assert (entry.timestamp, entry.level) == ("2026-10-07 15:44:12", "INFO")
    assert entry.module == "dashboard_report"
    assert entry.message == "Fetching data"


def test_generic_message_not_mistaken_for_module():
    entry = parse_line("2026-10-07 15:44:12 INFO Fetching data")
    assert entry.module is None
    assert entry.message == "Fetching data"


def test_bracketed_level_with_timestamp():
    entry = parse_line("2026-10-07 15:44:12 [INFO] Fetching data")
    assert entry.timestamp == "2026-10-07 15:44:12"
    assert entry.level == "INFO"
    assert entry.message == "Fetching data"
    assert entry.logger is None


def test_bracket_without_context_keeps_message_with_colon():
    entry = parse_line("[INFO] Failed: reason unknown")
    assert entry.logger is None
    assert entry.message == "Failed: reason unknown"


def test_python_basic_config():
    entry = PythonLogParser().parse("WARNING:root:Disk usage at 91%")
    assert entry is not None
    assert (entry.level, entry.logger, entry.message) == ("WARNING", "root", "Disk usage at 91%")


def test_python_dashed_format():
    entry = PythonLogParser().parse("2026-10-07 15:44:14,512 - myapp.db - ERROR - Slow query")
    assert entry is not None
    assert (entry.logger, entry.level, entry.message) == ("myapp.db", "ERROR", "Slow query")
    assert entry.timestamp == "2026-10-07 15:44:14,512"


def test_json_logs():
    line = (
        '{"timestamp": "2026-10-07T15:44:12", "level": "INFO", "module": "dashboard_report", '
        '"message": "Fetching dashboard", "trace_id": "abc", "user_id": "123", "host": "h1"}'
    )
    entry = parse_line(line)
    assert entry.timestamp == "2026-10-07T15:44:12"
    assert entry.level == "INFO"
    assert entry.module == "dashboard_report"
    assert entry.message == "Fetching dashboard"
    assert (entry.trace_id, entry.user_id) == ("abc", "123")
    assert entry.extra == {"host": "h1"}


def test_json_alias_fields_and_exception():
    entry = JsonLogParser().parse(
        '{"time": 1790000000, "severity": "warn", "msg": "x", "user": "u1", "exception": "Boom"}'
    )
    assert entry is not None
    assert entry.level == "WARNING"
    assert entry.user_id == "u1"
    assert entry.exception == "Boom"
    assert entry.timestamp and entry.timestamp.startswith("20")


@pytest.mark.parametrize("line", ['{"foo": 1}', "{not json}", "[1, 2]", "{"])
def test_json_non_log_objects_are_raw(line):
    assert JsonLogParser().parse(line) is None
    assert parse_line(line).level == "RAW"


@pytest.mark.parametrize("line", ["", "garbage", "[UNKNOWN] [t=a] x - y", "2026-10-07 nonsense"])
def test_malformed_lines_become_raw_and_are_preserved(line):
    entry = parse_line(line)
    assert entry.level == "RAW"
    assert entry.message == line


def test_text_parser_returns_none_for_unknown():
    assert TextLogParser().parse("just text") is None


def test_ansi_codes_are_stripped_before_parsing():
    entry = parse_line("\x1b[32m[INFO]\x1b[0m [t=a mod=m] App - ok")
    assert entry.level == "INFO"
    assert entry.message == "ok"


def test_multiline_traceback_stays_attached():
    parser = StreamParser()
    lines = [
        "[ERROR] [t=a mod=db] Repo - Failed",
        "Traceback (most recent call last):",
        '  File "x.py", line 1, in f',
        "    boom()",
        "ValueError: nope",
        "[INFO] [t=a mod=db] Repo - Next",
        "stray line",
    ]
    entries = [parser.parse(line) for line in lines]
    assert [e.continuation for e in entries] == [False, True, True, True, True, False, False]
    assert entries[4].level == "RAW"
    assert entries[4].message == "ValueError: nope"
    assert entries[6].continuation is False


def test_indented_line_without_history_is_not_continuation():
    assert StreamParser().parse("   indented").continuation is False
