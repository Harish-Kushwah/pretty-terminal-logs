import pytest

from pretty_terminal_logs.config import (
    Config,
    config_from_env,
    config_from_mapping,
    load_config_file,
    parse_color,
    parse_level,
    resolve_config,
)
from pretty_terminal_logs.exceptions import ConfigError

FULL_YAML = """
theme: high-contrast
level: WARNING
color: auto
display:
  timestamp: false
  module: true
  logger: false
  context: true
  shorten_ids: false
context:
  fields:
    - trace_id
    - service
"""


def test_defaults_need_no_file():
    config = Config()
    assert config.theme == "default" and config.color is None and config.shorten_ids is True
    assert config.context_fields == ("trace_id", "user_id", "request_id", "api")


def test_full_config_file(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text(FULL_YAML, encoding="utf-8")
    config = load_config_file(path)
    assert config.theme == "high-contrast"
    assert config.level == 30
    assert config.color is None
    assert (config.show_timestamp, config.show_logger, config.shorten_ids) == (False, False, False)
    assert config.context_fields == ("trace_id", "service")


def test_empty_file_gives_defaults(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("", encoding="utf-8")
    assert load_config_file(path) == Config()


def test_precedence_file_then_env(tmp_path):
    path = tmp_path / "c.yaml"
    path.write_text("theme: minimal\nlevel: INFO\n", encoding="utf-8")
    config = resolve_config(path, {"PRETTY_LOG_LEVEL": "debug", "PRETTY_LOG_COLOR": "never"})
    assert config.theme == "minimal"  # from file
    assert config.level == 10  # env beats file
    assert config.color is False


def test_env_variables():
    config = config_from_env(
        Config(),
        {
            "PRETTY_LOG_THEME": "minimal",
            "PRETTY_LOG_SHORT_IDS": "false",
            "PRETTY_LOG_COLOR": "auto",
        },
    )
    assert (config.theme, config.shorten_ids, config.color) == ("minimal", False, None)


@pytest.mark.parametrize(
    "env",
    [
        {"PRETTY_LOG_COLOR": "purple"},
        {"PRETTY_LOG_SHORT_IDS": "maybe"},
        {"PRETTY_LOG_THEME": "neon"},
        {"PRETTY_LOG_LEVEL": "loud"},
    ],
)
def test_invalid_env(env):
    with pytest.raises(ConfigError):
        config_from_env(Config(), env)


def test_parse_helpers():
    assert parse_level("warn") == 30 and parse_level(10) == 10 and parse_level("25") == 25
    assert (
        parse_color("always") is True
        and parse_color(False) is False
        and parse_color("auto") is None
    )
    for bad in (True, "loud", None, 1.5):
        with pytest.raises(ConfigError):
            parse_level(bad)


def test_mapping_validation():
    with pytest.raises(ConfigError, match="mapping"):
        config_from_mapping(Config(), ["x"])
    with pytest.raises(ConfigError, match="unknown key"):
        config_from_mapping(Config(), {"display": {"colour": True}})
    assert config_from_mapping(Config(), None) == Config()
