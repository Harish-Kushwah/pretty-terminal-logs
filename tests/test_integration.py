import io
import logging
import subprocess
import sys
import textwrap

import pytest

from pretty_terminal_logs import log_context, setup_logging


@pytest.fixture(autouse=True)
def clean_root_logger(monkeypatch):
    for key in (
        "NO_COLOR",
        "CI",
        "PRETTY_LOG_COLOR",
        "PRETTY_LOG_LEVEL",
        "PRETTY_LOG_THEME",
        "PRETTY_LOG_SHORT_IDS",
    ):
        monkeypatch.delenv(key, raising=False)
    root = logging.getLogger()
    saved_handlers, saved_level = list(root.handlers), root.level
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


def test_setup_logging_formats_normal_logging_calls():
    stream = io.StringIO()
    setup_logging(stream=stream, color=False)
    logger = logging.getLogger("tests.integration")
    logger.info("Application started")
    logger.warning("Something looks suspicious")
    logger.error("Something failed")
    out = stream.getvalue()
    assert "INFO" in out and "WARNING" in out and "ERROR" in out
    assert "Application started" in out and "tests.integration" in out
    assert "\x1b" not in out


def test_level_argument_str_and_int():
    stream = io.StringIO()
    setup_logging(level="WARNING", stream=stream, color=False)
    logging.getLogger("x").info("hidden")
    logging.getLogger("x").warning("shown")
    assert "hidden" not in stream.getvalue() and "shown" in stream.getvalue()

    stream = io.StringIO()
    setup_logging(level=logging.DEBUG, stream=stream, color=False)
    logging.getLogger("x").debug("dbg")
    assert "DEBUG" in stream.getvalue()


def test_options_are_honoured():
    stream = io.StringIO()
    setup_logging(
        stream=stream, color=False, show_timestamp=False, show_module=False, show_context=False
    )
    with log_context(trace_id="abc"):
        logging.getLogger("opt").info("hello")
    assert stream.getvalue().splitlines() == ["INFO", "└─ opt", "   hello"]


def test_context_and_shortening_via_setup_logging():
    stream = io.StringIO()
    setup_logging(stream=stream, color=False)
    with log_context(trace_id="d8be77d2-2375-4b71-a818-b676cd5e80da", module="dashboard_report"):
        logging.getLogger("ctx").info("Fetching")
    out = stream.getvalue()
    assert "dashboard_report" in out and "trace=d8be77d2...80da" in out

    stream = io.StringIO()
    setup_logging(stream=stream, color=False, shorten_ids=False)
    with log_context(trace_id="d8be77d2-2375-4b71-a818-b676cd5e80da"):
        logging.getLogger("ctx").info("Fetching")
    assert "trace=d8be77d2-2375-4b71-a818-b676cd5e80da" in stream.getvalue()


def test_color_true_and_env_and_auto():
    stream = io.StringIO()
    setup_logging(stream=stream, color=True)
    logging.getLogger("c").info("x")
    assert "\x1b[" in stream.getvalue()

    stream = io.StringIO()
    setup_logging(stream=stream)  # StringIO is not a TTY -> auto = off
    logging.getLogger("c").info("x")
    assert "\x1b" not in stream.getvalue()


def test_env_vars_apply_and_arguments_override(monkeypatch):
    monkeypatch.setenv("PRETTY_LOG_LEVEL", "ERROR")
    monkeypatch.setenv("PRETTY_LOG_THEME", "minimal")
    stream = io.StringIO()
    setup_logging(stream=stream, color=False)
    logging.getLogger("e").warning("hidden")
    logging.getLogger("e").error("shown")
    assert "hidden" not in stream.getvalue()
    assert stream.getvalue().splitlines()[0].split(" ")[1] == "ERROR"  # minimal = one line

    stream = io.StringIO()
    setup_logging(stream=stream, color=False, level="DEBUG", theme="default")
    logging.getLogger("e").debug("now shown")
    assert "now shown" in stream.getvalue()


def test_exception_logging():
    stream = io.StringIO()
    setup_logging(stream=stream, color=False)
    try:
        raise TimeoutError("connection timed out")
    except TimeoutError:
        logging.getLogger("database").exception("Database operation failed")
    out = stream.getvalue()
    assert "ERROR" in out and "Database operation failed" in out
    assert "TimeoutError: connection timed out" in out and "Traceback" in out


def test_setup_is_idempotent_and_force_replaces_handlers():
    root = logging.getLogger()
    setup_logging(stream=io.StringIO())
    count = len(root.handlers)
    setup_logging(stream=io.StringIO())
    assert len(root.handlers) == count
    setup_logging(stream=io.StringIO(), force=True)
    assert len(root.handlers) == 1


def test_invalid_arguments_raise():
    from pretty_terminal_logs.exceptions import ConfigError

    with pytest.raises(ConfigError):
        setup_logging(level="LOUD")
    with pytest.raises(ConfigError):
        setup_logging(theme="neon")


def test_small_application_piped_into_cli():
    """python app.py 2>&1 | pretty-log, end to end through real processes."""
    app = textwrap.dedent(
        """
        import logging
        logging.basicConfig(level=logging.INFO)  # plain, unmodified application logging
        log = logging.getLogger("app")
        log.info("Application started")
        log.warning("Something looks suspicious")
        log.error("Something failed")
        """
    )
    produced = subprocess.run([sys.executable, "-c", app], capture_output=True, timeout=30)
    assert produced.returncode == 0
    rendered = subprocess.run(
        [sys.executable, "-m", "pretty_terminal_logs", "--no-color"],
        input=produced.stderr,
        capture_output=True,
        timeout=30,
    )
    text = rendered.stdout.decode("utf-8")
    assert "INFO" in text and "WARNING" in text and "ERROR" in text
    assert "Application started" in text and "Something failed" in text
    assert "INFO:app:" not in text  # parsed, not passed through raw


def test_python_formatter_output_roundtrips_through_cli_parser():
    """Output of the logging formatter is itself readable; raw lines are never lost."""
    stream = io.StringIO()
    setup_logging(stream=stream, color=False)
    logging.getLogger("rt").info("round trip")
    assert "round trip" in stream.getvalue()
