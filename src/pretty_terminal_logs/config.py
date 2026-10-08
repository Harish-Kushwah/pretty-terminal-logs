"""Configuration: defaults < config file < environment variables (< explicit arguments)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from .colors import get_theme
from .exceptions import ConfigError

DEFAULT_CONTEXT_FIELDS: tuple[str, ...] = ("trace_id", "user_id", "request_id", "api")

_LEVELS = {
    "NOTSET": 0,
    "DEBUG": 10,
    "INFO": 20,
    "WARN": 30,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
    "FATAL": 50,
}
_TRUE = {"true", "1", "yes", "on", "always"}
_FALSE = {"false", "0", "no", "off", "never"}


@dataclass(frozen=True)
class Config:
    """Resolved settings shared by the logging integration and the CLI."""

    theme: str = "default"
    #: Minimum level (numeric). ``None`` means "no filtering" (CLI) / INFO (``setup_logging``).
    level: int | None = None
    #: ``True``/``False`` force colors on/off; ``None`` means auto-detect.
    color: bool | None = None
    show_timestamp: bool = True
    show_module: bool = True
    show_logger: bool = True
    show_context: bool = True
    shorten_ids: bool = True
    context_fields: tuple[str, ...] = DEFAULT_CONTEXT_FIELDS
    #: Force the one-line layout regardless of theme.
    compact: bool = False
    #: Include the date in timestamps.
    verbose: bool = False

    def replace(self, **changes: Any) -> Config:
        """Return a copy with ``changes`` applied."""
        return replace(self, **changes)


def parse_level(value: object) -> int:
    """Convert ``"INFO"``, ``"20"`` or ``20`` to a numeric level."""
    if isinstance(value, bool):
        raise ConfigError(f"invalid log level {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().upper()
        if text in _LEVELS:
            return _LEVELS[text]
        if text.isdigit():
            return int(text)
    raise ConfigError(f"invalid log level {value!r} (use DEBUG, INFO, WARNING, ERROR, CRITICAL)")


def parse_bool(value: object, name: str = "value") -> bool:
    """Parse a boolean from a bool or a string like ``true``/``off``."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
    raise ConfigError(f"invalid boolean for {name}: {value!r}")


def parse_color(value: object) -> bool | None:
    """Parse ``auto`` (None), ``always``/true (True) or ``never``/false (False)."""
    if value is None or (isinstance(value, str) and value.strip().lower() == "auto"):
        return None
    return parse_bool(value, "color")


def parse_context_fields(value: object) -> tuple[str, ...]:
    """Validate a list of field names."""
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) and v for v in value):
        raise ConfigError("context.fields must be a list of field names")
    return tuple(value)


_TOP_KEYS = {"theme", "level", "color", "display", "context", "compact", "verbose"}
_DISPLAY_KEYS = {
    "timestamp": "show_timestamp",
    "module": "show_module",
    "logger": "show_logger",
    "context": "show_context",
    "shorten_ids": "shorten_ids",
}


def _section(data: Mapping[str, Any], key: str, allowed: set[str]) -> Mapping[str, Any]:
    section = data[key]
    if not isinstance(section, Mapping):
        raise ConfigError(f"'{key}' must be a mapping")
    unknown = sorted(set(section) - allowed)
    if unknown:
        raise ConfigError(f"unknown key(s) in '{key}': {', '.join(map(str, unknown))}")
    return section


def config_from_mapping(base: Config, data: object) -> Config:
    """Apply a parsed config document (see README) on top of ``base``."""
    if data is None:
        return base
    if not isinstance(data, Mapping):
        raise ConfigError("configuration must be a mapping of settings")
    unknown = sorted(set(data) - _TOP_KEYS, key=str)
    if unknown:
        raise ConfigError(f"unknown configuration key(s): {', '.join(map(str, unknown))}")

    changes: dict[str, Any] = {}
    if "theme" in data:
        if not isinstance(data["theme"], str):
            raise ConfigError("'theme' must be a string")
        changes["theme"] = get_theme(data["theme"]).name
    if "level" in data:
        changes["level"] = parse_level(data["level"])
    if "color" in data:
        changes["color"] = parse_color(data["color"])
    for key in ("compact", "verbose"):
        if key in data:
            changes[key] = parse_bool(data[key], key)
    if "display" in data:
        for key, value in _section(data, "display", set(_DISPLAY_KEYS)).items():
            changes[_DISPLAY_KEYS[key]] = parse_bool(value, f"display.{key}")
    if "context" in data:
        section = _section(data, "context", {"fields"})
        if "fields" in section:
            changes["context_fields"] = parse_context_fields(section["fields"])
    return base.replace(**changes)


def load_config_file(path: str | os.PathLike[str], base: Config | None = None) -> Config:
    """Load a YAML config file on top of ``base`` (defaults when omitted)."""
    base = base or Config()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config file {str(path)!r}: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {str(path)!r}: {exc}") from exc
    try:
        return config_from_mapping(base, data)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def config_from_env(base: Config, env: Mapping[str, str] | None = None) -> Config:
    """Apply ``PRETTY_LOG_COLOR/LEVEL/THEME/SHORT_IDS`` on top of ``base``."""
    env = os.environ if env is None else env
    changes: dict[str, Any] = {}
    try:
        if env.get("PRETTY_LOG_COLOR"):
            changes["color"] = parse_color(env["PRETTY_LOG_COLOR"])
        if env.get("PRETTY_LOG_LEVEL"):
            changes["level"] = parse_level(env["PRETTY_LOG_LEVEL"])
        if env.get("PRETTY_LOG_THEME"):
            changes["theme"] = get_theme(env["PRETTY_LOG_THEME"]).name
        if env.get("PRETTY_LOG_SHORT_IDS"):
            changes["shorten_ids"] = parse_bool(env["PRETTY_LOG_SHORT_IDS"], "PRETTY_LOG_SHORT_IDS")
    except ConfigError as exc:
        raise ConfigError(f"environment: {exc}") from exc
    return base.replace(**changes)


def resolve_config(
    path: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Build a :class:`Config` from defaults, then the optional file, then the environment."""
    config = Config()
    if path is not None:
        config = load_config_file(path, config)
    return config_from_env(config, env)
