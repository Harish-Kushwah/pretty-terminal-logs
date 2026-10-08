"""Attaching context: contextvars, a context manager, and a bound logger.

python examples/context.py
"""

import asyncio
import logging

from pretty_terminal_logs import (
    clear_context,
    get_context_logger,
    log_context,
    set_context,
    setup_logging,
)

setup_logging()
logger = logging.getLogger("app.dashboard")

# 1. Plain logging + contextvars: every record in this thread/task carries the context.
set_context(
    trace_id="d8be77d2-2375-4b71-a818-b676cd5e80da",
    user_id="22e2604a-b1e1-40c5-83b8-27312f6bcb71",
    module="dashboard_report",
)
logger.info("Fetching dashboard report")
clear_context()

# 2. Scoped context; the previous context is restored on exit.
with log_context(trace_id="abc", request_id="xyz"):
    logger.info("Inside the request")
logger.info("Outside the request")

# 3. A logger with fixed context (optional helper).
bound = get_context_logger("app.billing", user_id="123", module="billing")
bound.warning("Card declined", extra={"attempt": 2})


# 4. Context is isolated between asyncio tasks.
async def handle(name: str) -> None:
    with log_context(trace_id=name):
        await asyncio.sleep(0.01)
        logger.info("Handling %s", name)


async def main() -> None:
    await asyncio.gather(handle("task-A"), handle("task-B"))


asyncio.run(main())
