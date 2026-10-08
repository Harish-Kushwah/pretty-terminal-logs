"""Exception types raised by pretty-terminal-logs."""

from __future__ import annotations


class PrettyLogError(Exception):
    """Base class for all library errors."""


class ConfigError(PrettyLogError, ValueError):
    """Raised for invalid configuration (config file, environment variable or argument)."""
