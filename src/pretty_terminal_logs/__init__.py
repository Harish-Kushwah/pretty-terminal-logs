"""pretty-terminal-logs: make application logs readable in the terminal."""

from __future__ import annotations

from importlib import metadata

from .context import clear_context, get_context_logger, log_context, set_context
from .formatter import setup_logging

try:
    __version__ = metadata.version("pretty-terminal-logs")
except metadata.PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.1.0"

__all__ = [
    "__version__",
    "clear_context",
    "get_context_logger",
    "log_context",
    "set_context",
    "setup_logging",
]
