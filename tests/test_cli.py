import io
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from pretty_terminal_logs.cli import follow_file, main

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sample.log"
APP_LINE = (
    "[INFO] [t=d8be77d2-2375-4b71-a818-b676cd5e80da u=22e2604a-b1e1-40c5-83b8-27312f6bcb71 "
    "mod=dashboard_report api= req=] DashboardReportRepository - Fetching from "
    "v_material_with_chemical_and_msds_compliance\n"
)


def run(argv, stdin_text="", env=None, monkeypatch=None):
    if monkeypatch:
        for key in (
            "NO_COLOR",
            "CI",
            "PRETTY_LOG_COLOR",
            "PRETTY_LOG_LEVEL",
            "PRETTY_LOG_THEME",
            "PRETTY_LOG_SHORT_IDS",
        ):
            monkeypatch.delenv(key, raising=False)
        for key, value in (env or {}).items():
            monkeypatch.setenv(key, value)
    out, err = io.StringIO(), io.StringIO()
    code = main(argv, stdin=io.StringIO(stdin_text), stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def test_stdin_pipe_renders_spec_example(monkeypatch):
    code, out, _ = run(["--no-color"], APP_LINE, monkeypatch=monkeypatch)
    assert code == 0
    assert out.splitlines() == [
        "--:--:-- │ INFO     │ dashboard_report",
        "          └─ DashboardReportRepository",
        "             Fetching from v_material_with_chemical_and_msds_compliance",
        "             trace=d8be77d2...80da │ user=22e2604a...cb71",
    ]


def test_sample_file_from_stdin(monkeypatch):
    code, out, _ = run(["--no-color"], SAMPLE.read_text(encoding="utf-8"), monkeypatch=monkeypatch)
    assert code == 0
    assert "\x1b" not in out
    for expected in (
        "WARNING  │ utils",
        "CRITICAL │ core",
        "RAW",
        "Fetching dashboard",
        "TimeoutError: connection timed out",
        "this line is not in any known format",
    ):
        assert expected in out


def test_file_argument(monkeypatch):
    code, out, _ = run(["--no-color", str(SAMPLE)], monkeypatch=monkeypatch)
    assert code == 0 and "DashboardReportRepository" in out


def test_no_color_has_no_escape_codes_and_color_forces_them(monkeypatch):
    assert "\x1b" not in run(["--no-color"], APP_LINE, monkeypatch=monkeypatch)[1]
    assert "\x1b[36mINFO" in run(["--color"], APP_LINE, monkeypatch=monkeypatch)[1]


def test_auto_color_is_off_for_non_tty_and_env_override(monkeypatch):
    assert "\x1b" not in run([], APP_LINE, monkeypatch=monkeypatch)[1]
    _, out, _ = run([], APP_LINE, env={"PRETTY_LOG_COLOR": "always"}, monkeypatch=monkeypatch)
    assert "\x1b[" in out
    # CLI argument beats the environment variable
    _, out, _ = run(
        ["--no-color"], APP_LINE, env={"PRETTY_LOG_COLOR": "always"}, monkeypatch=monkeypatch
    )
    assert "\x1b" not in out


def test_no_short_ids(monkeypatch):
    _, out, _ = run(["--no-color", "--no-short-ids"], APP_LINE, monkeypatch=monkeypatch)
    assert "trace=d8be77d2-2375-4b71-a818-b676cd5e80da" in out and "..." not in out


def test_env_short_ids_and_cli_override(monkeypatch):
    env = {"PRETTY_LOG_SHORT_IDS": "false"}
    assert "..." not in run(["--no-color"], APP_LINE, env=env, monkeypatch=monkeypatch)[1]


def test_minimal_theme_and_compact(monkeypatch):
    _, out, _ = run(
        ["--no-color", "--theme", "minimal"],
        "2026-10-07 15:44:12 INFO dashboard_report Fetching data\n",
        monkeypatch=monkeypatch,
    )
    assert out == "15:44:12 INFO dashboard_report Fetching data\n"
    _, out, _ = run(
        ["--no-color", "--compact"],
        "2026-10-07 15:44:12 INFO dashboard_report Fetching data\n",
        monkeypatch=monkeypatch,
    )
    assert out == "15:44:12 INFO dashboard_report Fetching data\n"


def test_level_filter_hides_entry_and_its_traceback(monkeypatch):
    text = (
        "[INFO] [t=a mod=m] App - quiet\n"
        "[ERROR] [t=a mod=m] App - loud\n"
        "Traceback (most recent call last):\n"
        '  File "x.py", line 1\n'
        "ValueError: boom\n"
    )
    _, out, _ = run(["--no-color", "--level", "ERROR"], text, monkeypatch=monkeypatch)
    assert "quiet" not in out and "loud" in out and "ValueError: boom" in out
    text2 = text.replace("ERROR", "DEBUG")
    _, out, _ = run(["--no-color", "--level", "ERROR"], text2, monkeypatch=monkeypatch)
    assert out == ""  # entry and its traceback are both hidden


def test_blank_lines_skipped_and_raw_kept(monkeypatch):
    _, out, _ = run(["--no-color"], "\n\nplain text\n", monkeypatch=monkeypatch)
    assert out.splitlines() == ["--:--:-- │ RAW", "          └─ plain text"]


def test_help_and_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    for option in (
        "--color",
        "--no-color",
        "--config",
        "--theme",
        "--compact",
        "--verbose",
        "--no-short-ids",
        "--follow",
    ):
        assert option in help_text
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "pretty-log" in capsys.readouterr().out


def test_config_file_is_applied(tmp_path, monkeypatch):
    cfg = tmp_path / "pretty-log.yaml"
    cfg.write_text(
        "theme: minimal\ncolor: never\ndisplay:\n  shorten_ids: false\n", encoding="utf-8"
    )
    _, out, _ = run(["--config", str(cfg)], APP_LINE, monkeypatch=monkeypatch)
    assert out.startswith("--:--:-- INFO dashboard_report DashboardReportRepository:")
    assert "trace=d8be77d2-2375-4b71-a818-b676cd5e80da" in out


@pytest.mark.parametrize(
    "content",
    [
        "theme: [unclosed",
        "nonsense: 1",
        "theme: neon",
        "level: LOUD",
        "display:\n  timestamp: maybe",
        "- a list",
        "context:\n  fields: nope",
    ],
)
def test_invalid_config_is_reported(tmp_path, monkeypatch, content):
    cfg = tmp_path / "bad.yaml"
    cfg.write_text(content, encoding="utf-8")
    code, out, err = run(["--config", str(cfg)], APP_LINE, monkeypatch=monkeypatch)
    assert code == 2 and out == ""
    assert err.startswith("pretty-log: error:")


def test_missing_config_file(monkeypatch):
    code, _, err = run(["--config", "does-not-exist.yaml"], "", monkeypatch=monkeypatch)
    assert code == 2 and "cannot read config file" in err


def test_invalid_theme_and_env(monkeypatch):
    assert run(["--theme", "neon"], "", monkeypatch=monkeypatch)[0] == 2
    code, _, err = run([], "", env={"PRETTY_LOG_LEVEL": "LOUD"}, monkeypatch=monkeypatch)
    assert code == 2 and "environment" in err


def test_missing_input_file(monkeypatch):
    code, _, err = run(["nope.log"], "", monkeypatch=monkeypatch)
    assert code == 1 and "nope.log" in err


def test_subprocess_pipe_end_to_end():
    proc = subprocess.run(
        [sys.executable, "-m", "pretty_terminal_logs", "--no-color"],
        input=APP_LINE.encode(),
        capture_output=True,
        timeout=30,
    )
    assert proc.returncode == 0
    text = proc.stdout.decode("utf-8")
    assert "INFO     │ dashboard_report" in text
    assert "trace=d8be77d2...80da" in text


# -- follow mode -------------------------------------------------------------------------


def test_follow_tail_partial_lines_and_truncation(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(b"old1\nold2\nold3\n")
    lines = follow_file(str(path), poll_interval=0.01, tail_lines=2)
    assert [next(lines), next(lines)] == ["old2\n", "old3\n"]

    handle = path.open("ab")
    handle.write(b"partial ")
    handle.flush()
    timer = threading.Timer(0.15, lambda: (handle.write(b"line\n"), handle.flush()))
    timer.start()
    assert next(lines) == "partial line\n"  # waited for the newline
    timer.join()
    handle.close()

    path.write_bytes(b"fresh\n")  # truncation / rotation
    assert next(lines) == "fresh\n"
    lines.close()


def test_follow_stops_on_request(tmp_path):
    path = tmp_path / "app.log"
    path.write_bytes(b"a\n")
    state = {"stop": False}
    gen = follow_file(
        str(path), poll_interval=0.01, tail_lines=1, should_stop=lambda: state["stop"]
    )
    assert next(gen) == "a\n"
    state["stop"] = True
    assert list(gen) == []


def test_follow_missing_file_is_reported(monkeypatch):
    code, _, err = run(["--follow", "nope.log"], "", monkeypatch=monkeypatch)
    assert code == 1 and "nope.log" in err
