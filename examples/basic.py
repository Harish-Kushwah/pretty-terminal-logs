"""Minimal usage: one setup call, then ordinary logging.

python examples/basic.py
"""

import logging

from pretty_terminal_logs import setup_logging

setup_logging(level=logging.DEBUG)

logger = logging.getLogger(__name__)

logger.debug("Loading settings")
logger.info("Application started")
logger.warning("Something looks suspicious", extra={"timeout": "361.2s"})
logger.error("Something failed")

try:
    {}["missing"]
except KeyError:
    logger.exception("Database operation failed")
