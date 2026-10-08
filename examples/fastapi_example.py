"""FastAPI integration (optional): pip install "pretty-terminal-logs[fastapi]" uvicorn

uvicorn examples.fastapi_example:app --app-dir . --log-level warning
curl localhost:8000/v1/dashboard -H "x-request-id: abc123"
"""

import logging

from fastapi import FastAPI

from pretty_terminal_logs import setup_logging
from pretty_terminal_logs.fastapi import LoggingMiddleware

setup_logging()

app = FastAPI()
app.add_middleware(LoggingMiddleware)

logger = logging.getLogger("app.dashboard")


@app.get("/v1/dashboard")
async def dashboard() -> dict[str, bool]:
    logger.info("Building dashboard")  # automatically carries req=<request id>
    return {"ok": True}
